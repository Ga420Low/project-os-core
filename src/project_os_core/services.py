from __future__ import annotations

from dataclasses import dataclass

from .config import RuntimeConfig, load_runtime_config
from .database import CanonicalDatabase
from .embedding import EmbeddingStrategy, choose_embedding_strategy
from .gateway.service import GatewayService
from .memory.store import MemoryStore
from .observability import StructuredLogger
from .orchestration.graph import CanonicalMissionGraph
from .paths import PathPolicy, ProjectPaths, build_project_paths, ensure_project_roots
from .router.service import MissionRouter
from .runtime.journal import LocalJournal
from .runtime.store import RuntimeStore
from .secrets import SecretResolver


@dataclass(slots=True)
class AppServices:
    config: RuntimeConfig
    paths: ProjectPaths
    path_policy: PathPolicy
    secret_resolver: SecretResolver
    embedding_strategy: EmbeddingStrategy
    database: CanonicalDatabase
    journal: LocalJournal
    memory: MemoryStore
    runtime: RuntimeStore
    router: MissionRouter
    gateway: GatewayService
    orchestration: CanonicalMissionGraph
    logger: StructuredLogger

    def close(self) -> None:
        self.memory.close()
        self.database.close()


def build_app_services(config_path: str | None = None, policy_path: str | None = None) -> AppServices:
    config = load_runtime_config(config_path=config_path, policy_path=policy_path)
    paths = build_project_paths(config)
    ensure_project_roots(paths)
    path_policy = PathPolicy(paths)
    secret_resolver = SecretResolver(config.secret_config, repo_root=config.repo_root)
    secret_resolver.migrate_repo_dotenv()
    embedding_strategy = choose_embedding_strategy(config, secret_resolver)
    database = CanonicalDatabase(paths.canonical_db_path, vector_dimensions=embedding_strategy.dimensions)
    journal = LocalJournal(database, paths.journal_file_path)
    logger = StructuredLogger(paths, path_policy)
    memory = MemoryStore(database, paths, path_policy, embedding_strategy, secret_resolver)
    runtime = RuntimeStore(database, paths, path_policy, journal)
    router = MissionRouter(
        database=database,
        runtime=runtime,
        path_policy=path_policy,
        secret_resolver=secret_resolver,
        execution_policy=config.execution_policy,
    )
    gateway = GatewayService(
        database=database,
        journal=journal,
        router=router,
        memory=memory,
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
        database=database,
        journal=journal,
        memory=memory,
        runtime=runtime,
        router=router,
        gateway=gateway,
        orchestration=orchestration,
        logger=logger,
    )
