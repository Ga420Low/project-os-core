from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from ..config import RetrievalSidecarConfig
from ..database import CanonicalDatabase
from ..models import RetrievalContext

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{1,}")
_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "au",
    "aux",
    "avec",
    "ce",
    "ces",
    "cette",
    "dans",
    "de",
    "des",
    "du",
    "en",
    "est",
    "et",
    "for",
    "from",
    "il",
    "is",
    "je",
    "la",
    "le",
    "les",
    "mais",
    "of",
    "on",
    "or",
    "ou",
    "par",
    "pas",
    "pour",
    "que",
    "qui",
    "sur",
    "the",
    "to",
    "un",
    "une",
    "with",
}


@dataclass(slots=True)
class _ScoredCandidate:
    raw_hit: dict[str, Any]
    candidate_key: str
    candidate_source: str
    text: str
    tokens: set[str]
    created_at: str | None
    base_score: float
    vector_score: float
    lexical_score: float
    session_recall_boost: float
    recency_boost: float
    diversity_penalty: float = 0.0
    final_score: float = 0.0


class RetrievalSidecar:
    def __init__(self, database: CanonicalDatabase, config: RetrievalSidecarConfig):
        self.database = database
        self.config = config

    def apply(
        self,
        *,
        context: RetrievalContext,
        collect_base_hits: Callable[[str, int], list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        if not self.config.enabled:
            return collect_base_hits(context.query, context.limit)[: context.limit]

        per_source_limit = max(context.limit, int(self.config.max_candidates_per_source))
        primary_hits = collect_base_hits(context.query, per_source_limit)
        expansion_terms = self._expand_query_terms(context, primary_hits)
        expanded_query = self._expanded_query(context.query, expansion_terms)

        collected = self._merge_hits(primary_hits, [])
        if self.config.query_expansion and expanded_query != context.query:
            collected = self._merge_hits(collected, collect_base_hits(expanded_query, per_source_limit))
        if self.config.session_recall:
            collected = self._merge_hits(collected, self._session_recall_hits(context))

        scored = self._score_candidates(context, collected, expansion_terms)
        reranked = self._rerank_with_mmr(scored, limit=context.limit)
        return [self._materialize_hit(candidate, expansion_terms, expanded_query) for candidate in reranked]

    def _expand_query_terms(self, context: RetrievalContext, seed_hits: list[dict[str, Any]]) -> list[str]:
        if not self.config.query_expansion:
            return []
        additions: list[str] = []
        for value in (
            context.project_id,
            context.mission_id,
            context.branch_name,
            context.target_profile,
            context.requested_worker,
            context.channel,
            context.surface,
            context.thread_id,
            context.external_thread_id,
            context.conversation_key,
        ):
            if value:
                additions.extend(self._tokenize(value))
        for tag in context.tags:
            additions.extend(self._tokenize(tag))
        metadata_keywords = context.metadata.get("keywords")
        if isinstance(metadata_keywords, list):
            for item in metadata_keywords:
                additions.extend(self._tokenize(str(item)))
        for hit in seed_hits[: self.config.max_candidates_per_source]:
            record = hit.get("record")
            if isinstance(record, dict):
                for tag in record.get("tags") or []:
                    additions.extend(self._tokenize(str(tag)))
                metadata = record.get("metadata")
                if isinstance(metadata, dict):
                    clean_content = metadata.get("clean_content")
                    if isinstance(clean_content, str):
                        additions.extend(self._tokenize(clean_content)[:2])
        seen: set[str] = set(self._tokenize(context.query))
        result: list[str] = []
        for token in additions:
            if token in seen or len(token) < 3:
                continue
            seen.add(token)
            result.append(token)
            if len(result) >= 8:
                break
        return result

    @staticmethod
    def _expanded_query(query: str, additions: list[str]) -> str:
        if not additions:
            return query
        return f"{query} {' '.join(additions)}".strip()

    def _merge_hits(self, left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for hit in [*left, *right]:
            key = str(hit.get("memory_id") or hit.get("_candidate_key") or "")
            if not key:
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = hit
                continue
            if self._candidate_preference(hit) > self._candidate_preference(existing):
                merged[key] = hit
                continue
            if hit.get("source") == "hybrid":
                existing["source"] = "hybrid"
                existing["openmemory"] = hit.get("openmemory")
        return list(merged.values())

    def _candidate_preference(self, hit: dict[str, Any]) -> float:
        trace = hit.get("retrieval_trace")
        if isinstance(trace, dict) and "base_score" in trace:
            return float(trace["base_score"])
        distance = hit.get("distance")
        if distance is not None:
            return self._distance_to_score(float(distance))
        if hit.get("source") in {"session_thread_recall", "recent_session_briefing"}:
            return 0.55
        return 0.35

    def _score_candidates(
        self,
        context: RetrievalContext,
        hits: list[dict[str, Any]],
        expansion_terms: list[str],
    ) -> list[_ScoredCandidate]:
        query_tokens = set(self._tokenize(context.query))
        expanded_tokens = set(expansion_terms)
        scored: list[_ScoredCandidate] = []
        for hit in hits:
            record = hit.get("record")
            text = self._candidate_text(record)
            tokens = set(self._tokenize(text))
            lexical_score = self._lexical_score(query_tokens | expanded_tokens, tokens)
            vector_score = self._vector_score(hit)
            base_score = max(vector_score, lexical_score)
            session_recall_boost = self._session_recall_boost(hit)
            recency_boost = self._recency_boost(hit, record)
            candidate_key = str(hit.get("memory_id") or hit.get("_candidate_key") or "")
            scored.append(
                _ScoredCandidate(
                    raw_hit=hit,
                    candidate_key=candidate_key,
                    candidate_source=str(hit.get("source") or "unknown"),
                    text=text,
                    tokens=tokens,
                    created_at=self._candidate_created_at(hit, record),
                    base_score=base_score,
                    vector_score=vector_score,
                    lexical_score=lexical_score,
                    session_recall_boost=session_recall_boost,
                    recency_boost=recency_boost,
                    final_score=base_score + session_recall_boost + recency_boost,
                )
            )
        scored.sort(
            key=lambda item: (
                -item.final_score,
                -self._timestamp_sort_key(item.created_at),
                item.candidate_key,
            )
        )
        return scored

    def _rerank_with_mmr(self, candidates: list[_ScoredCandidate], *, limit: int) -> list[_ScoredCandidate]:
        if not candidates:
            return []
        selected: list[_ScoredCandidate] = []
        remaining = list(candidates)
        lambda_weight = min(1.0, max(0.0, float(self.config.mmr_lambda)))
        while remaining and len(selected) < limit:
            best: _ScoredCandidate | None = None
            best_score: float | None = None
            for candidate in remaining:
                max_similarity = 0.0
                if selected:
                    max_similarity = max(self._token_similarity(candidate.tokens, item.tokens) for item in selected)
                diversity_penalty = (1.0 - lambda_weight) * max_similarity
                mmr_score = (lambda_weight * candidate.final_score) - diversity_penalty
                if best is None or mmr_score > float(best_score) or (
                    math.isclose(mmr_score, float(best_score))
                    and self._timestamp_sort_key(candidate.created_at) > self._timestamp_sort_key(best.created_at)
                ) or (
                    math.isclose(mmr_score, float(best_score))
                    and self._timestamp_sort_key(candidate.created_at) == self._timestamp_sort_key(best.created_at)
                    and candidate.candidate_key < best.candidate_key
                ):
                    best = candidate
                    best_score = mmr_score
                    candidate.diversity_penalty = diversity_penalty
                    candidate.final_score = mmr_score
            if best is None:
                break
            selected.append(best)
            remaining = [item for item in remaining if item.candidate_key != best.candidate_key]
        return selected

    def _materialize_hit(
        self,
        candidate: _ScoredCandidate,
        expansion_terms: list[str],
        expanded_query: str,
    ) -> dict[str, Any]:
        hit = dict(candidate.raw_hit)
        trace = dict(hit.get("retrieval_trace") or {})
        trace.update(
            {
                "candidate_source": candidate.candidate_source,
                "base_score": round(candidate.base_score, 6),
                "session_recall_boost": round(candidate.session_recall_boost, 6),
                "recency_boost": round(candidate.recency_boost, 6),
                "diversity_penalty": round(candidate.diversity_penalty, 6),
                "final_score": round(candidate.final_score, 6),
                "vector_score": round(candidate.vector_score, 6),
                "lexical_score": round(candidate.lexical_score, 6),
                "expanded_query": expanded_query,
                "expanded_query_terms": list(expansion_terms),
            }
        )
        hit["retrieval_trace"] = trace
        hit.pop("_candidate_key", None)
        return hit

    def _session_recall_hits(self, context: RetrievalContext) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        hits.extend(self._thread_session_hits(context))
        hits.extend(self._recent_run_hits(context))
        return hits[: max(context.limit, self.config.recent_session_limit)]

    def _thread_session_hits(self, context: RetrievalContext) -> list[dict[str, Any]]:
        channel = str(context.channel or "").strip()
        if not channel:
            return []
        keys = [
            key
            for key in (
                context.conversation_key,
                context.external_thread_id,
                context.thread_id,
            )
            if key
        ]
        params: list[Any] = [channel]
        clauses = ["ce.channel = ?"]
        if keys:
            placeholders = ", ".join("?" for _ in keys)
            clauses.append(f"(ce.conversation_key IN ({placeholders}) OR dtb.external_thread_id IN ({placeholders}) OR dtb.thread_id IN ({placeholders}))")
            params.extend(keys)
            params.extend(keys)
            params.extend(keys)
        params.append(max(1, int(self.config.recent_session_limit)))
        rows = self.database.fetchall(
            f"""
            SELECT ce.event_id, ce.channel, ce.conversation_key, ce.thread_ref_json, ce.message_json, ce.created_at,
                   gdr.dispatch_id, gdr.reply_json, gdr.metadata_json,
                   cmc.summary AS candidate_summary, cmc.content AS candidate_content, cmc.tags_json, cmc.payload_json,
                   dtb.binding_id, dtb.binding_kind
            FROM channel_events AS ce
            LEFT JOIN gateway_dispatch_results AS gdr ON gdr.channel_event_id = ce.event_id
            LEFT JOIN conversation_memory_candidates AS cmc ON cmc.source_event_id = ce.event_id
            LEFT JOIN discord_thread_bindings AS dtb ON dtb.channel_event_id = ce.event_id
            WHERE {" AND ".join(clauses)}
            ORDER BY ce.created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        hits: list[dict[str, Any]] = []
        for row in rows:
            message = self._json_loads(row["message_json"])
            reply = self._json_loads(row["reply_json"])
            candidate_payload = self._json_loads(row["payload_json"])
            dispatch_metadata = self._json_loads(row["metadata_json"])
            record_metadata = {
                "session_recall": True,
                "recall_kind": "thread",
                "channel": str(row["channel"]),
                "conversation_key": row["conversation_key"],
                "thread_ref": self._json_loads(row["thread_ref_json"]),
                "dispatch_id": row["dispatch_id"],
                "binding_id": row["binding_id"],
                "binding_kind": row["binding_kind"],
                "privacy_view": self._session_privacy_view(candidate_payload, dispatch_metadata),
                "sensitivity_class": candidate_payload.get("sensitivity_class") or dispatch_metadata.get("sensitivity_class"),
            }
            record = {
                "content": self._session_content(
                    message_text=str(message.get("text") or row["candidate_content"] or ""),
                    reply_summary=str(reply.get("summary") or ""),
                ),
                "user_id": context.user_id,
                "project_id": context.project_id,
                "mission_id": context.mission_id,
                "summary": str(row["candidate_summary"] or message.get("text") or "").strip()[:240],
                "tags": self._json_list(row["tags_json"]),
                "metadata": record_metadata,
                "created_at": str(row["created_at"]),
            }
            if not self._record_visible(record, context):
                continue
            hits.append(
                {
                    "memory_id": f"session_event:{row['event_id']}",
                    "_candidate_key": f"session_event:{row['event_id']}",
                    "source": "session_thread_recall",
                    "record": record,
                    "distance": 0.0,
                }
            )
        return hits

    def _recent_run_hits(self, context: RetrievalContext) -> list[dict[str, Any]]:
        branch_name = str(context.branch_name or "").strip()
        target_profile = str(context.target_profile or "").strip()
        if not branch_name and not target_profile:
            return []
        params: list[Any] = []
        where_parts: list[str] = []
        if branch_name and target_profile:
            where_parts.append("(req.branch_name = ? OR req.target_profile = ?)")
            params.extend([branch_name, target_profile])
        elif branch_name:
            where_parts.append("req.branch_name = ?")
            params.append(branch_name)
        else:
            where_parts.append("req.target_profile = ?")
            params.append(target_profile)
        params.append(max(1, int(self.config.recent_session_limit)))
        rows = self.database.fetchall(
            f"""
            SELECT req.run_request_id, req.branch_name, req.objective, req.target_profile, req.status AS request_status,
                   req.updated_at AS request_updated_at,
                   res.run_id, res.model, res.status AS result_status, res.updated_at AS result_updated_at
            FROM api_run_requests AS req
            LEFT JOIN api_run_results AS res ON res.run_request_id = req.run_request_id
            WHERE {" AND ".join(where_parts)}
            ORDER BY COALESCE(res.updated_at, req.updated_at) DESC
            LIMIT ?
            """,
            tuple(params),
        )
        hits: list[dict[str, Any]] = []
        for row in rows:
            text = self._run_briefing_text(row)
            record = {
                "content": text,
                "user_id": context.user_id,
                "project_id": context.project_id,
                "mission_id": context.mission_id,
                "summary": text[:240],
                "tags": ["recent_session_briefing", str(row["branch_name"])],
                "metadata": {
                    "session_recall": True,
                    "recall_kind": "recent_session_briefing",
                    "privacy_view": "clean",
                    "branch_name": str(row["branch_name"]),
                    "target_profile": str(row["target_profile"]) if row["target_profile"] else None,
                    "run_id": str(row["run_id"]) if row["run_id"] else None,
                },
                "created_at": str(row["result_updated_at"] or row["request_updated_at"]),
            }
            hits.append(
                {
                    "memory_id": f"run_briefing:{row['run_request_id']}",
                    "_candidate_key": f"run_briefing:{row['run_request_id']}",
                    "source": "recent_session_briefing",
                    "record": record,
                    "distance": 0.0,
                }
            )
        return hits

    @staticmethod
    def _run_briefing_text(row: Any) -> str:
        parts = [f"Run {row['branch_name']}: {row['objective']}"]
        if row["target_profile"]:
            parts.append(f"profile={row['target_profile']}")
        parts.append(f"request_status={row['request_status']}")
        if row["result_status"]:
            parts.append(f"result_status={row['result_status']}")
        if row["model"]:
            parts.append(f"model={row['model']}")
        return " | ".join(parts)

    @staticmethod
    def _json_loads(value: Any) -> dict[str, Any]:
        if not value:
            return {}
        try:
            loaded = json.loads(str(value))
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _json_list(value: Any) -> list[str]:
        if not value:
            return []
        try:
            loaded = json.loads(str(value))
            if isinstance(loaded, list):
                return [str(item) for item in loaded]
        except Exception:
            return []
        return []

    @staticmethod
    def _session_content(*, message_text: str, reply_summary: str) -> str:
        parts: list[str] = []
        if message_text.strip():
            parts.append(f"user: {message_text.strip()}")
        if reply_summary.strip():
            parts.append(f"project_os: {reply_summary.strip()}")
        return "\n".join(parts).strip()

    @staticmethod
    def _session_privacy_view(candidate_payload: dict[str, Any], dispatch_metadata: dict[str, Any]) -> str:
        sensitivity = str(
            candidate_payload.get("sensitivity_class")
            or dispatch_metadata.get("sensitivity_class")
            or ""
        ).strip()
        if sensitivity == "s3_local":
            return "full"
        return "clean"

    @staticmethod
    def _record_visible(record: dict[str, Any], context: RetrievalContext) -> bool:
        if context.include_private_full:
            return True
        metadata = record.get("metadata")
        if not isinstance(metadata, dict):
            return True
        return str(metadata.get("privacy_view") or "").strip().lower() != "full"

    def _session_recall_boost(self, hit: dict[str, Any]) -> float:
        source = str(hit.get("source") or "")
        if source == "session_thread_recall":
            return 0.35
        if source == "recent_session_briefing":
            return 0.18
        return 0.0

    def _recency_boost(self, hit: dict[str, Any], record: dict[str, Any] | None) -> float:
        created_at = self._candidate_created_at(hit, record)
        timestamp = self._parse_timestamp(created_at)
        if timestamp is None:
            return 0.0
        age_days = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds() / 86400.0)
        half_life = max(1, int(self.config.recency_half_life_days))
        decay = math.exp(-math.log(2.0) * (age_days / half_life))
        return 0.2 * decay

    @staticmethod
    def _candidate_created_at(hit: dict[str, Any], record: dict[str, Any] | None) -> str | None:
        if isinstance(record, dict):
            created_at = record.get("created_at")
            if created_at:
                return str(created_at)
        trace = hit.get("record")
        if isinstance(trace, dict) and trace.get("created_at"):
            return str(trace.get("created_at"))
        return None

    def _vector_score(self, hit: dict[str, Any]) -> float:
        distance = hit.get("distance")
        if distance is not None:
            return self._distance_to_score(float(distance))
        openmemory = hit.get("openmemory")
        if isinstance(openmemory, dict):
            for key in ("score", "similarity", "relevance"):
                if key in openmemory:
                    try:
                        return max(0.0, min(1.0, float(openmemory[key])))
                    except Exception:
                        continue
        return 0.0

    @staticmethod
    def _distance_to_score(distance: float) -> float:
        return 1.0 / (1.0 + max(distance, 0.0))

    @staticmethod
    def _lexical_score(query_tokens: set[str], candidate_tokens: set[str]) -> float:
        if not query_tokens or not candidate_tokens:
            return 0.0
        overlap = len(query_tokens & candidate_tokens)
        if overlap <= 0:
            return 0.0
        return overlap / max(1, len(query_tokens))

    @staticmethod
    def _candidate_text(record: dict[str, Any] | None) -> str:
        if not isinstance(record, dict):
            return ""
        content = str(record.get("content") or "").strip()
        if content:
            return content
        summary = str(record.get("summary") or "").strip()
        if summary:
            return summary
        metadata = record.get("metadata")
        if isinstance(metadata, dict):
            return str(metadata.get("clean_content") or "").strip()
        return ""

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _timestamp_sort_key(value: str | None) -> float:
        parsed = RetrievalSidecar._parse_timestamp(value)
        return parsed.timestamp() if parsed else 0.0

    @staticmethod
    def _token_similarity(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        union = left | right
        if not union:
            return 0.0
        return len(left & right) / len(union)

    @staticmethod
    def _tokenize(value: str) -> list[str]:
        pieces: list[str] = []
        for raw in _TOKEN_RE.findall(value or ""):
            lowered = raw.strip().lower()
            if not lowered:
                continue
            pieces.append(lowered)
            if any(char.isupper() for char in raw):
                pieces.extend(part.lower() for part in _CAMEL_RE.split(raw) if part)
            pieces.extend(
                part.lower()
                for part in re.split(r"[/_.:-]+", raw)
                if part
            )
        result: list[str] = []
        seen: set[str] = set()
        for item in pieces:
            if item in _STOPWORDS or len(item) < 2 or item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result
