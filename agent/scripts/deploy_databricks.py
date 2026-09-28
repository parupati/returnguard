"""Deploy ReturnGuard as a scheduled Databricks Job (serverless), so it runs with no laptop and no human.

1. Stores every setting from agent/.env in the Databricks secret scope `returnguard` (read by returnguard.jobs).
2. Uploads the `returnguard` package and the task file to /Workspace/Users/<you>/returnguard/.
3. Creates, or updates, the job "ReturnGuard agent" on a schedule (hourly by default).
4. With --run-now, triggers one run immediately and waits for the result.

    uv run --env-file .env python scripts/deploy_databricks.py --run-now
    uv run --env-file .env python scripts/deploy_databricks.py --paused          # deploy without the schedule running
"""

import argparse
import os
from datetime import timedelta
from pathlib import Path

from databricks.sdk.errors import ResourceAlreadyExists
from databricks.sdk.service import compute, jobs
from databricks.sdk.service.workspace import ImportFormat

from returnguard.config import load_databricks_settings
from returnguard.jobs import DEFAULT_SECRET_SCOPE, SETTING_KEYS
from returnguard.lakehouse import workspace_client

AGENT_DIR = Path(__file__).resolve().parent.parent
PACKAGE_DIR = AGENT_DIR / "src" / "returnguard"
TASK_FILE = AGENT_DIR / "deploy" / "run_returnguard.py"

JOB_NAME = "ReturnGuard agent"
HOURLY = "0 0 * * * ?"
DEPENDENCIES = ["pydantic>=2.8", "google-genai>=1.30", "httpx>=0.27", "databricks-sdk>=0.60"]


def store_settings(w, scope: str) -> None:
    try:
        w.secrets.create_scope(scope=scope)
        print(f"Created secret scope '{scope}'")
    except ResourceAlreadyExists:
        print(f"Secret scope '{scope}' already exists")
    stored = 0
    for key in SETTING_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            w.secrets.put_secret(scope=scope, key=key, string_value=value)
            stored += 1
    print(f"Stored {stored} settings in '{scope}' (values not shown)")


def upload_code(w, base: str) -> str:
    w.workspace.mkdirs(f"{base}/returnguard")
    for source in sorted(PACKAGE_DIR.glob("*.py")):
        w.workspace.upload(f"{base}/returnguard/{source.name}", source.read_bytes(), format=ImportFormat.AUTO, overwrite=True)
    task_path = f"{base}/run_returnguard.py"
    w.workspace.upload(task_path, TASK_FILE.read_bytes(), format=ImportFormat.AUTO, overwrite=True)
    print(f"Uploaded {len(list(PACKAGE_DIR.glob('*.py')))} modules and the task file to {base}")
    return task_path


def job_settings(task_path: str, cron: str, paused: bool) -> jobs.JobSettings:
    return jobs.JobSettings(
        name=JOB_NAME,
        description="Autonomous return-risk intervention agent: Shopify + Databricks + Bloomreach + Gemini.",
        max_concurrent_runs=1,
        schedule=jobs.CronSchedule(
            quartz_cron_expression=cron,
            timezone_id="UTC",
            pause_status=jobs.PauseStatus.PAUSED if paused else jobs.PauseStatus.UNPAUSED,
        ),
        environments=[
            jobs.JobEnvironment(
                environment_key="returnguard",
                spec=compute.Environment(environment_version="2", dependencies=DEPENDENCIES),
            )
        ],
        tasks=[
            jobs.Task(
                task_key="run_agent",
                description="One ReturnGuard cycle: resolve outcomes, then decide and act on new orders",
                spark_python_task=jobs.SparkPythonTask(python_file=task_path, source=jobs.Source.WORKSPACE),
                environment_key="returnguard",
                timeout_seconds=1800,
            )
        ],
        tags={"project": "returnguard"},
    )


def create_or_update_job(w, settings: jobs.JobSettings) -> int:
    existing = next(iter(w.jobs.list(name=JOB_NAME)), None)
    if existing:
        w.jobs.reset(job_id=existing.job_id, new_settings=settings)
        print(f"Updated job '{JOB_NAME}' (id {existing.job_id})")
        return existing.job_id
    created = w.jobs.create(**{field: getattr(settings, field) for field in (
        "name", "description", "max_concurrent_runs", "schedule", "environments", "tasks", "tags"
    )})
    print(f"Created job '{JOB_NAME}' (id {created.job_id})")
    return created.job_id


def run_now(w, host: str, job_id: int) -> None:
    print("Running the job now (serverless start-up takes a minute or two)...")
    run = w.jobs.run_now(job_id=job_id).result(timeout=timedelta(minutes=25))
    state = run.state.result_state.value if run.state and run.state.result_state else "UNKNOWN"
    print(f"Run finished: {state}  {host}/jobs/{job_id}/runs/{run.run_id}")
    for task in run.tasks or []:
        output = w.jobs.get_run_output(run_id=task.run_id)
        if output.logs:
            print("----- task output -----")
            print(output.logs[-4000:])
        if output.error:
            print(f"----- task error -----\n{output.error}\n{output.error_trace or ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cron", default=HOURLY, help="Quartz cron, default hourly")
    parser.add_argument("--paused", action="store_true", help="Deploy with the schedule paused")
    parser.add_argument("--run-now", action="store_true", help="Trigger one run and wait for it")
    args = parser.parse_args()

    settings = load_databricks_settings()
    w = workspace_client(settings)
    me = w.current_user.me().user_name
    base = f"/Workspace/Users/{me}/returnguard"

    store_settings(w, DEFAULT_SECRET_SCOPE)
    task_path = upload_code(w, base)
    job_id = create_or_update_job(w, job_settings(task_path, args.cron, args.paused))
    print(f"Job: {settings.host}/jobs/{job_id}")
    if args.run_now:
        run_now(w, settings.host, job_id)


if __name__ == "__main__":
    main()
