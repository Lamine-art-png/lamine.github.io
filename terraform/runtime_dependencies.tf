data "aws_caller_identity" "current" {}

locals {
  managed_runtime_enabled = var.enable_managed_runtime_dependencies
  runtime_object_backend  = local.managed_runtime_enabled ? "s3" : var.connector_object_storage_backend
  runtime_object_bucket   = local.managed_runtime_enabled ? aws_s3_bucket.connector_objects[0].bucket : var.connector_object_bucket
  runtime_object_region   = trimspace(var.connector_object_region) != "" ? var.connector_object_region : data.aws_region.current.name
  runtime_object_endpoint = local.managed_runtime_enabled ? "" : var.connector_object_endpoint_url

  runtime_redis_url = local.managed_runtime_enabled ? format(
    "rediss://default:%s@%s:6379/0",
    urlencode(random_password.redis_auth_token[0].result),
    aws_elasticache_replication_group.connector_queue[0].primary_endpoint_address,
  ) : var.redis_url

  runtime_vault_key = local.managed_runtime_enabled ? random_id.connector_vault_key[0].b64_url : var.connector_credential_master_key
  runtime_oauth_key = local.managed_runtime_enabled ? random_password.oauth_state_signing_key[0].result : var.oauth_state_signing_key
  runtime_app_secret = local.managed_runtime_enabled ? random_password.application_secret[0].result : var.secret_key
}

resource "random_password" "redis_auth_token" {
  count            = local.managed_runtime_enabled ? 1 : 0
  length           = 48
  special          = true
  override_special = "!#$%&*+-=?^_~"
}

resource "random_id" "connector_vault_key" {
  count       = local.managed_runtime_enabled ? 1 : 0
  byte_length = 32
}

resource "random_password" "oauth_state_signing_key" {
  count   = local.managed_runtime_enabled ? 1 : 0
  length  = 64
  special = false
}

resource "random_password" "application_secret" {
  count   = local.managed_runtime_enabled ? 1 : 0
  length  = 64
  special = false
}

resource "aws_s3_bucket" "connector_objects" {
  count = local.managed_runtime_enabled ? 1 : 0

  bucket        = substr(lower("${replace(var.project, "_", "-")}-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.name}-connector-objects"), 0, 63)
  force_destroy = var.connector_object_force_destroy

  tags = {
    Project     = var.project
    Purpose     = "connector-object-custody"
    DataClass   = "customer-evidence"
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket_public_access_block" "connector_objects" {
  count = local.managed_runtime_enabled ? 1 : 0

  bucket = aws_s3_bucket.connector_objects[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "connector_objects" {
  count = local.managed_runtime_enabled ? 1 : 0

  bucket = aws_s3_bucket.connector_objects[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "connector_objects" {
  count = local.managed_runtime_enabled ? 1 : 0

  bucket = aws_s3_bucket.connector_objects[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "connector_objects" {
  count = local.managed_runtime_enabled ? 1 : 0

  bucket = aws_s3_bucket.connector_objects[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "connector_objects" {
  count = local.managed_runtime_enabled ? 1 : 0

  bucket = aws_s3_bucket.connector_objects[0].id

  depends_on = [aws_s3_bucket_versioning.connector_objects]

  rule {
    id     = "raw-connector-retention"
    status = "Enabled"

    filter {
      prefix = "${var.connector_object_prefix}/tenants/"
    }

    expiration {
      days = var.connector_object_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_elasticache_subnet_group" "connector_queue" {
  count = local.managed_runtime_enabled ? 1 : 0

  name       = "${var.project}-connector-queue"
  subnet_ids = length(var.db_subnet_ids) > 0 ? var.db_subnet_ids : var.ecs_subnet_ids

  tags = {
    Project = var.project
    Purpose = "connector-worker-queue"
  }
}

resource "aws_security_group" "connector_queue" {
  count = local.managed_runtime_enabled ? 1 : 0

  name_prefix = "${var.project}-redis-"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Redis TLS from ECS tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_api.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project
    Purpose = "connector-worker-queue"
  }
}

resource "aws_elasticache_replication_group" "connector_queue" {
  count = local.managed_runtime_enabled ? 1 : 0

  replication_group_id = substr("${var.project}-connector-queue", 0, 40)
  description          = "AGRO-AI durable connector worker queue"

  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  port                 = 6379
  num_cache_clusters   = 1 + var.redis_replica_count
  parameter_group_name = "default.redis7"

  automatic_failover_enabled = var.redis_replica_count > 0
  multi_az_enabled            = var.redis_replica_count > 0
  at_rest_encryption_enabled  = true
  transit_encryption_enabled  = true
  auth_token                  = random_password.redis_auth_token[0].result

  subnet_group_name  = aws_elasticache_subnet_group.connector_queue[0].name
  security_group_ids = [aws_security_group.connector_queue[0].id]

  snapshot_retention_limit = 1
  apply_immediately        = true

  tags = {
    Project   = var.project
    Purpose   = "connector-worker-queue"
    ManagedBy = "terraform"
  }
}

resource "aws_secretsmanager_secret" "runtime" {
  count = local.managed_runtime_enabled ? 1 : 0

  name_prefix             = "${var.project}/runtime/"
  recovery_window_in_days = 7

  tags = {
    Project   = var.project
    Purpose   = "runtime-secret-custody"
    ManagedBy = "terraform"
  }
}

resource "aws_secretsmanager_secret_version" "runtime" {
  count = local.managed_runtime_enabled ? 1 : 0

  secret_id = aws_secretsmanager_secret.runtime[0].id
  secret_string = jsonencode({
    SECRET_KEY                         = local.runtime_app_secret
    REDIS_URL                          = local.runtime_redis_url
    CONNECTOR_CREDENTIAL_MASTER_KEY    = local.runtime_vault_key
    CONNECTOR_CREDENTIAL_KEYS_JSON     = var.connector_credential_keys_json
    OAUTH_STATE_SIGNING_KEY            = local.runtime_oauth_key
  })
}

data "aws_iam_policy_document" "connector_object_access" {
  count = local.managed_runtime_enabled ? 1 : 0

  statement {
    sid = "ListConnectorBucket"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
    ]
    resources = [aws_s3_bucket.connector_objects[0].arn]
  }

  statement {
    sid = "ReadWriteConnectorObjects"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.connector_objects[0].arn}/${var.connector_object_prefix}/tenants/*"]
  }
}

resource "aws_iam_role_policy" "connector_object_access" {
  count = local.managed_runtime_enabled ? 1 : 0

  name   = "${var.project}-connector-object-access"
  role   = aws_iam_role.ecs_task.id
  policy = data.aws_iam_policy_document.connector_object_access[0].json
}

data "aws_iam_policy_document" "runtime_secret_access" {
  count = local.managed_runtime_enabled ? 1 : 0

  statement {
    sid       = "ReadRuntimeSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.runtime[0].arn]
  }
}

resource "aws_iam_role_policy" "runtime_secret_access" {
  count = local.managed_runtime_enabled ? 1 : 0

  name   = "${var.project}-runtime-secret-access"
  role   = aws_iam_role.ecs_task_execution.id
  policy = data.aws_iam_policy_document.runtime_secret_access[0].json
}

output "connector_object_bucket" {
  value       = local.runtime_object_bucket
  description = "Connector object bucket used by API and workers."
}

output "managed_redis_endpoint" {
  value       = local.managed_runtime_enabled ? aws_elasticache_replication_group.connector_queue[0].primary_endpoint_address : null
  description = "Managed Redis primary endpoint. The authenticated URL remains secret."
}

output "runtime_secret_arn" {
  value       = local.managed_runtime_enabled ? aws_secretsmanager_secret.runtime[0].arn : null
  description = "Secrets Manager ARN injected into ECS task definitions."
}
