from __future__ import annotations

from dataclasses import dataclass

from .api_runs.service import ApiRunService
from .config import RuntimeConfig, load_runtime_config
from .database import CanonicalDatabase
from .deep_research import DeepResearchService
from .gateway.openclaw_live import OpenClawLiveService
from .github.service import GitHubLearningService
from .embedding import EmbeddingStrategy, choose_embedding_strategy
from .gateway.service import GatewayService
from .learning.service import LearningService
from .local_model import LocalModelClient
from .memory.blocks import MemoryBlockStore
from .memory.curator import SleeptimeCuratorService
from .memory.os_service import MemoryOSService
from .memory.store import MemoryStore
from .memory.temporal_graph import TemporalGraphService
from .memory.thoughts import ThoughtMemoryService
from .memory.tiering import TierManagerService
from .mission.chain import MissionChainService
from .observability import StructuredLogger
from .orchestration.graph import CanonicalMissionGraph
from .paths import PathPolicy, ProjectPaths, build_project_paths, ensure_project_roots
from .router.service import MissionRouter
from .scheduler.service import SchedulerService
from .runtime.journal import LocalJournal
from .runtime.store import RuntimeStore
from .secrets import SecretResolver
from .session.state import PersistentSessionState


@dataclass(slots=True)
class AppServices:
    config: RuntimeConfig
    paths: ProjectPaths
    path_policy: PathPolicy
    secret_resolver: SecretResolver
    embedding_strategy: EmbeddingStrategy
    local_model_client: LocalModelClient
    database: CanonicalDatabase
    journal: LocalJournal
    memory: MemoryStore
    memory_blocks: MemoryBlockStore
    memory_os: MemoryOSService
    thoughts: ThoughtMemoryService
    curator: SleeptimeCuratorService
    temporal_graph: TemporalGraphService
    tier_manager: TierManagerService
    learning: LearningService
    github: GitHubLearningService
    runtime: RuntimeStore
    router: MissionRouter
    session_state: PersistentSessionState
    gateway: GatewayService
    deep_research: DeepResearchService
    openclaw: OpenClawLiveService
    orchestration: CanonicalMissionGraph
    api_runs: ApiRunService
    chain: MissionChainService
    scheduler: SchedulerService
    logger: StructuredLogger

    def close(self) -> None:
        self.memory.close()
        self.temporal_graph.close()
        self.database.close()


def build_app_services(config_path: str | None = None, policy_path: str | None = None) -> AppServices:
    config = load_runtime_config(config_path=config_path, policy_path=policy_path)
    paths = build_project_paths(config)
    ensure_project_roots(paths)
    path_policy = PathPolicy(paths)
    secret_resolver = SecretResolver(config.secret_config, repo_root=config.repo_root)
    secret_resolver.migrate_repo_dotenv()
    embedding_strategy = choose_embedding_strategy(config, secret_resolver)
    local_model_client = LocalModelClient(
        enabled=config.execution_policy.local_model_enabled,
        provider=config.execution_policy.local_model_provider,
        base_url=config.execution_policy.local_model_base_url,
        model=config.execution_policy.local_model_name,
        timeout_seconds=config.execution_policy.local_model_timeout_seconds,
        health_timeout_seconds=config.execution_policy.local_model_health_timeout_seconds,
    )
    database = CanonicalDatabase(paths.canonical_db_path, vector_dimensions=embedding_strategy.dimensions)
    journal = LocalJournal(database, paths.journal_file_path)
    logger = StructuredLogger(paths, path_policy)
    memory = MemoryStore(
        database,
        paths,
        path_policy,
        embedding_strategy,
        secret_resolver,
        retrieval_sidecar_config=config.memory_config.retrieval_sidecar,
    )
    memory_blocks = MemoryBlockStore(
        database=database,
        paths=paths,
        path_policy=path_policy,
        config=config.memory_config.blocks,
    )
    temporal_graph = TemporalGraphService(
        database=database,
        paths=paths,
        path_policy=path_policy,
        config=config.memory_config.temporal_graph,
    )
    memory_os = MemoryOSService(
        database=database,
        journal=journal,
        paths=paths,
        path_policy=path_policy,
        config=config.memory_config,
        blocks=memory_blocks,
        temporal_graph=temporal_graph,
    )
    thoughts = ThoughtMemoryService(
        database=database,
        memory_os=memory_os,
        thoughts_config=config.memory_config.thoughts,
        supersession_config=config.memory_config.supersession,
    )
    memory_os.attach_thought_service(thoughts)
    memory.attach_memory_os(memory_os)
    tier_manager = TierManagerService(
        config=config.tier_manager_config,
        database=database,
        memory=memory,
        paths=paths,
        path_policy=path_policy,
        journal=journal,
    )
    memory.attach_tier_manager(tier_manager)
    learning = LearningService(
        database=database,
        journal=journal,
        memory=memory,
        paths=paths,
        path_policy=path_policy,
        auto_sync_runbook_deferred=config.learning_config.auto_sync_runbook_deferred,
        runbook_deferred_globs=config.learning_config.runbook_deferred_globs,
    )
    github = GitHubLearningService(
        config=config.github_config,
        database=database,
        learning=learning,
        journal=journal,
        logger=logger,
        repo_root=config.repo_root,
    )
    runtime = RuntimeStore(database, paths, path_policy, journal)
    router = MissionRouter(
        database=database,
        runtime=runtime,
        path_policy=path_policy,
        secret_resolver=secret_resolver,
        execution_policy=config.execution_policy,
        local_model_client=local_model_client,
    )
    api_runs = ApiRunService(
        database=database,
        journal=journal,
        paths=paths,
        path_policy=path_policy,
        secret_resolver=secret_resolver,
        logger=logger,
        router=router,
        execution_policy=config.execution_policy,
        dashboard_config=config.api_dashboard_config,
        learning=learning,
    )
    chain = MissionChainService(database=database, api_runs=api_runs, journal=journal)
    scheduler = SchedulerService(
        database=database,
        journal=journal,
        logger=logger,
        github_config=config.github_config,
        memory_config=config.memory_config,
    )
    curator = SleeptimeCuratorService(
        database=database,
        journal=journal,
        config=config.memory_config.curator,
        blocks=memory_blocks,
        memory_os=memory_os,
        thoughts=thoughts,
        temporal_graph=temporal_graph,
        local_model_client=local_model_client,
        secret_resolver=secret_resolver,
        default_openai_model=config.execution_policy.default_model,
    )
    session_state = PersistentSessionState(database=database, api_runs=api_runs)
    deep_research = DeepResearchService(
        paths=paths,
        path_policy=path_policy,
        secret_resolver=secret_resolver,
        journal=journal,
        logger=logger,
        api_runs=api_runs,
        config_path=config.storage_config_path,
        policy_path=config.runtime_policy_path,
        default_model=config.execution_policy.default_model,
        default_reasoning_effort=config.execution_policy.default_reasoning_effort,
    )
    gateway = GatewayService(
        database=database,
        journal=journal,
        router=router,
        memory=memory,
        session_state=session_state,
        paths=paths,
        path_policy=path_policy,
        secret_resolver=secret_resolver,
        local_model_client=local_model_client,
        deep_research=deep_research,
    )
    openclaw = OpenClawLiveService(
        config=config,
        paths=paths,
        path_policy=path_policy,
        runtime=runtime,
        database=database,
        logger=logger,
        local_model_client=local_model_client,
    )
    orchestration = CanonicalMissionGraph(
        database=database,
        journal=journal,
    )
    return AppServices(
        config=config,
        paths=paths,
        path_policy=path_policy,
        secret_resolver=secret_resolver,
        embedding_strategy=embedding_strategy,
        local_model_client=local_model_client,
        database=database,
        journal=journal,
        memory=memory,
        memory_blocks=memory_blocks,
        memory_os=memory_os,
        thoughts=thoughts,
        curator=curator,
        temporal_graph=temporal_graph,
        tier_manager=tier_manager,
        learning=learning,
        github=github,
        runtime=runtime,
        router=router,
        session_state=session_state,
        gateway=gateway,
        deep_research=deep_research,
        openclaw=openclaw,
        orchestration=orchestration,
        api_runs=api_runs,
        chain=chain,
        scheduler=scheduler,
        logger=logger,
    )
