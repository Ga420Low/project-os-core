from __future__ import annotations

from dataclasses import dataclass

from .api_runs.service import ApiRunService
from .config import RuntimeConfig, load_runtime_config
from .database import CanonicalDatabase
from .gateway.openclaw_live import OpenClawLiveService
from .github.service import GitHubLearningService
from .embedding import EmbeddingStrategy, choose_embedding_strategy
from .gateway.service import GatewayService
from .learning.service import LearningService
from .memory.store import MemoryStore
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
    database: CanonicalDatabase
    journal: LocalJournal
    memory: MemoryStore
    tier_manager: TierManagerService
    learning: LearningService
    github: GitHubLearningService
    runtime: RuntimeStore
    router: MissionRouter
    session_state: PersistentSessionState
    gateway: GatewayService
    openclaw: OpenClawLiveService
    orchestration: CanonicalMissionGraph
    api_runs: ApiRunService
    chain: MissionChainService
    scheduler: SchedulerService
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
    )
    api_runs = ApiRunService(
        database=database,
        journal=journal,
        paths=paths,
        path_policy=path_policy,
        secret_resolver=secret_resolver,
        logger=logger,
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
    )
    session_state = PersistentSessionState(database=database, api_runs=api_runs)
    gateway = GatewayService(
        database=database,
        journal=journal,
        router=router,
        memory=memory,
        session_state=session_state,
        secret_resolver=secret_resolver,
    )
    openclaw = OpenClawLiveService(
        config=config,
        paths=paths,
        path_policy=path_policy,
        runtime=runtime,
        database=database,
        logger=logger,
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
        tier_manager=tier_manager,
        learning=learning,
        github=github,
        runtime=runtime,
        router=router,
        session_state=session_state,
        gateway=gateway,
        openclaw=openclaw,
        orchestration=orchestration,
        api_runs=api_runs,
        chain=chain,
        scheduler=scheduler,
        logger=logger,
    )
