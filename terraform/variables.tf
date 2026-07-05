variable "project" {
  type        = string
  description = "Project name prefix"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID for all networking"
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Public subnets (ALB typically lives here)"
}

variable "ecs_subnet_ids" {
  type        = list(string)
  description = "Subnets for ECS tasks"
}

variable "api_container_port" {
  type        = number
  description = "Container port for the API"
  default     = 8000
}

variable "image_tag" {
  description = "Docker image tag to deploy (usually a git SHA)"
  type        = string
  default     = "latest"
}

variable "openweather_api_key" {
  type        = string
  description = "OpenWeather API key"
  sensitive   = true

  validation {
    condition     = length(trimspace(var.openweather_api_key)) > 0
    error_message = "openweather_api_key must be set (TF_VAR_openweather_api_key or -var)."
  }
}

variable "wiseconn_api_key" {
  type        = string
  description = "WiseConn API key"
  sensitive   = true
  default     = ""
}

variable "database_url" {
  type        = string
  description = "External PostgreSQL connection string. Leave empty to use the managed RDS URL emitted by this stack."
  sensitive   = true
  default     = ""
}

variable "secret_key" {
  type        = string
  description = "Application secret key for JWT signing. Supply from the deployment secret store."
  sensitive   = true
  default     = ""
}

variable "db_subnet_ids" {
  type        = list(string)
  description = "Private subnets for RDS and Redis"
  default     = []
}

variable "sync_interval_minutes" {
  type        = number
  description = "Legacy WiseConn sync interval in minutes. The API process scheduler remains disabled in production."
  default     = 15
}

variable "enable_managed_runtime_dependencies" {
  type        = bool
  description = "Provision production-like Redis, private S3 connector storage, and runtime secret custody."
  default     = false
}

variable "worker_desired_count" {
  type        = number
  description = "Number of independent connector worker tasks."
  default     = 1

  validation {
    condition     = var.worker_desired_count >= 0 && var.worker_desired_count <= 100
    error_message = "worker_desired_count must be between 0 and 100."
  }
}

variable "worker_cpu" {
  type        = number
  description = "Fargate CPU units for the connector worker task."
  default     = 512
}

variable "worker_memory" {
  type        = number
  description = "Fargate memory MiB for the connector worker task."
  default     = 1024
}

variable "redis_url" {
  type        = string
  description = "Externally managed Redis URL when managed runtime dependencies are disabled. Prefer rediss://."
  sensitive   = true
  default     = ""
}

variable "redis_node_type" {
  type        = string
  description = "ElastiCache node type for the managed Redis replication group."
  default     = "cache.t4g.micro"
}

variable "redis_replica_count" {
  type        = number
  description = "Number of read replicas in addition to the primary managed Redis node."
  default     = 1

  validation {
    condition     = var.redis_replica_count >= 0 && var.redis_replica_count <= 5
    error_message = "redis_replica_count must be between 0 and 5."
  }
}

variable "task_queue_stream" {
  type        = string
  description = "Redis Stream used for durable connector work."
  default     = "agroai:tasks"
}

variable "task_queue_group" {
  type        = string
  description = "Redis consumer group used by connector workers."
  default     = "agroai-workers"
}

variable "task_queue_stream_maxlen" {
  type        = number
  description = "Approximate maximum number of entries retained in the Redis task stream."
  default     = 100000
}

variable "task_queue_lease_seconds" {
  type        = number
  description = "Database lease duration used for worker crash recovery."
  default     = 120
}

variable "task_queue_max_attempts" {
  type        = number
  description = "Maximum durable worker attempts before a job becomes terminally failed."
  default     = 5
}

variable "connector_object_storage_backend" {
  type        = string
  description = "Connector object-storage backend: s3, r2, s3_compatible, or disabled."
  default     = "disabled"

  validation {
    condition     = contains(["disabled", "s3", "r2", "s3_compatible"], var.connector_object_storage_backend)
    error_message = "connector_object_storage_backend must be disabled, s3, r2, or s3_compatible."
  }
}

variable "connector_object_bucket" {
  type        = string
  description = "Existing connector object bucket when managed runtime dependencies are disabled."
  default     = ""
}

variable "connector_object_prefix" {
  type        = string
  description = "Prefix used for tenant/connector object namespaces."
  default     = "agroai"
}

variable "connector_object_endpoint_url" {
  type        = string
  description = "Optional S3-compatible endpoint URL, for example Cloudflare R2."
  default     = ""
}

variable "connector_object_region" {
  type        = string
  description = "Region for the configured connector object store. Defaults to the Terraform AWS region when empty."
  default     = ""
}

variable "connector_object_retention_days" {
  type        = number
  description = "Retention period for managed raw connector objects."
  default     = 90

  validation {
    condition     = var.connector_object_retention_days >= 7
    error_message = "connector_object_retention_days must be at least 7 days."
  }
}

variable "connector_object_force_destroy" {
  type        = bool
  description = "Allow Terraform to delete a non-empty managed connector bucket. Keep false outside disposable environments."
  default     = false
}

variable "connector_credential_master_key" {
  type        = string
  description = "URL-safe base64 32-byte connector-vault key for externally managed secret custody."
  sensitive   = true
  default     = ""
}

variable "connector_credential_keys_json" {
  type        = string
  description = "Optional versioned connector-vault keyring JSON for rotation."
  sensitive   = true
  default     = ""
}

variable "connector_credential_active_key_version" {
  type        = string
  description = "Active connector-vault key version."
  default     = "v1"
}

variable "oauth_state_signing_key" {
  type        = string
  description = "Dedicated OAuth-state HMAC signing key for externally managed secret custody."
  sensitive   = true
  default     = ""
}

variable "db_password" {
  type        = string
  description = "Optional managed-RDS master password. Leave empty to generate one in Terraform."
  sensitive   = true
  default     = ""
}

variable "db_instance_class" {
  type        = string
  description = "RDS instance class."
  default     = "db.t3.micro"
}

variable "db_multi_az" {
  type        = bool
  description = "Enable Multi-AZ RDS deployment."
  default     = false
}

variable "db_deletion_protection" {
  type        = bool
  description = "Protect the managed RDS instance from accidental deletion."
  default     = false
}

variable "db_skip_final_snapshot" {
  type        = bool
  description = "Skip final RDS snapshot on destroy. Keep false for production."
  default     = true
}
