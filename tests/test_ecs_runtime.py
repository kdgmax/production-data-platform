from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from data_platform.ecs_runtime import database_url_from_environment

ROOT = Path(__file__).parents[1]


def test_database_url_encodes_credentials_and_requires_tls() -> None:
    url = database_url_from_environment(
        {
            "DATA_PLATFORM_DB_HOST": "database.internal",
            "DATA_PLATFORM_DB_PORT": "5432",
            "DATA_PLATFORM_DB_NAME": "data/platform",
            "DATA_PLATFORM_DB_USERNAME": "pipeline+runtime",
            "DATA_PLATFORM_DB_PASSWORD": "not/a:real@secret",
        }
    )

    assert url == (
        "postgresql://pipeline%2Bruntime:not%2Fa%3Areal%40secret@"
        "database.internal:5432/data%2Fplatform?sslmode=require"
    )


def test_database_url_reports_missing_keys_without_secret_values() -> None:
    with pytest.raises(RuntimeError) as error:
        database_url_from_environment(
            {
                "DATA_PLATFORM_DB_HOST": "database.internal",
                "DATA_PLATFORM_DB_PASSWORD": "do-not-leak",
            }
        )

    assert "DATA_PLATFORM_DB_PORT" in str(error.value)
    assert "do-not-leak" not in str(error.value)


def test_ecs_image_runs_as_nonroot_with_dedicated_entrypoint() -> None:
    dockerfile = (ROOT / "Dockerfile.ecs").read_text()

    assert "USER pipeline" in dockerfile
    assert "useradd --create-home --uid 10001 pipeline" in dockerfile
    assert 'ENTRYPOINT ["data-platform-ecs-run"]' in dockerfile
    assert "USER root" not in dockerfile


def test_deployment_workflow_is_manual_approved_and_keyless() -> None:
    path = ROOT / ".github" / "workflows" / "deploy-ecs.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    text = path.read_text()

    assert "workflow_dispatch" in workflow["on"]
    assert workflow["jobs"]["deploy"]["environment"] == "production"
    assert workflow["permissions"] == {"contents": "read", "id-token": "write"}
    assert "aws-actions/configure-aws-credentials@v6" in text
    assert "assignPublicIp=DISABLED" in text
    assert "AWS_ACCESS_KEY_ID" not in text
    assert "AWS_SECRET_ACCESS_KEY" not in text

