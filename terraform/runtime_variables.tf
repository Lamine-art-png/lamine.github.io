variable "ecs_runtime_environment" {
  type        = map(string)
  description = "Additional non-secret environment variables injected into API and worker tasks."
  default     = {}
}

variable "ecs_runtime_secrets" {
  type        = map(string)
  description = "ECS secret references keyed by environment variable name. Values must be Secrets Manager or SSM parameter ARNs."
  sensitive   = true
  default     = {}
}
