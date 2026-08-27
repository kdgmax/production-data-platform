from __future__ import annotations

import re
from pathlib import Path

import hcl2

INFRASTRUCTURE = Path(__file__).parents[1] / "infrastructure"


def terraform_text() -> str:
    return "\n".join(path.read_text() for path in sorted(INFRASTRUCTURE.glob("*.tf")))


def test_all_terraform_files_parse() -> None:
    files = sorted(INFRASTRUCTURE.glob("*.tf"))
    assert files
    for path in files:
        with path.open() as source:
            assert hcl2.load(source) is not None, path


def test_storage_has_encryption_versioning_retention_and_no_public_access() -> None:
    storage = (INFRASTRUCTURE / "storage.tf").read_text()

    for setting in (
        "block_public_acls       = true",
        "block_public_policy     = true",
        "ignore_public_acls      = true",
        "restrict_public_buckets = true",
        'status = "Enabled"',
        'sse_algorithm     = "aws:kms"',
        'variable = "aws:SecureTransport"',
        'variable = "s3:x-amz-server-side-encryption-customer-algorithm"',
        "days_after_initiation = 7",
    ):
        assert setting in storage


def test_database_is_private_encrypted_protected_and_secret_managed() -> None:
    database = (INFRASTRUCTURE / "database.tf").read_text()

    assert "publicly_accessible    = false" in database
    assert "storage_encrypted     = true" in database
    assert "manage_master_user_password   = true" in database
    assert "deletion_protection       = var.protect_database" in database
    assert re.search(r"backup_retention_period\s*=\s*7", database)
    assert "max_allocated_storage = 100" in database
    assert 'cidr_blocks = ["0.0.0.0/0"]' not in database


def test_network_is_private_and_runtime_policy_is_resource_scoped() -> None:
    network = (INFRASTRUCTURE / "network.tf").read_text()
    iam = (INFRASTRUCTURE / "iam.tf").read_text()

    assert "map_public_ip_on_launch = false" in network
    assert 'vpc_endpoint_type = "Gateway"' in network
    assert "aws_internet_gateway" not in network
    assert "aws_nat_gateway" not in network
    assert "resources = [\"*\"]" not in iam
    assert 'identifiers = ["ecs-tasks.amazonaws.com"]' in iam


def test_kms_key_rotation_and_log_service_access_are_configured() -> None:
    encryption = (INFRASTRUCTURE / "encryption.tf").read_text()

    assert "enable_key_rotation     = true" in encryption
    assert "AllowCloudWatchLogsEncryption" in encryption
    assert 'variable = "kms:EncryptionContext:aws:logs:arn"' in encryption
    assert 'values   = ["arn:${data.aws_partition.current.partition}:logs:' in encryption


def test_ci_formats_initializes_and_validates_terraform() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text()

    assert "hashicorp/setup-terraform@v4" in workflow
    assert "terraform fmt -check -recursive infrastructure" in workflow
    assert "terraform -chdir=infrastructure init -backend=false -input=false" in workflow
    assert "terraform -chdir=infrastructure validate" in workflow


def test_required_versions_are_pinned() -> None:
    versions = (INFRASTRUCTURE / "versions.tf").read_text()

    assert 'required_version = "~> 1.15.0"' in versions
    assert 'version = "~> 6.60.0"' in versions
    assert "aws_s3_bucket_public_access_block" in terraform_text()
