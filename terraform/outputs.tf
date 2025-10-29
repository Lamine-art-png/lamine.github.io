output "vpc_id" {
  value = module.vpc.vpc_id
}

output "db_endpoint" {
  value = try(module.db.db_instance_endpoint, module.db.db_instance_address)
}

output "db_port" {
  value = try(module.db.db_instance_port, 5432) # adjust default if not Postgres
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecs_cluster_arn" {
  value = module.ecs.cluster_arn
}

output "ecs_cluster_name" {
  value = try(module.ecs.cluster_name, null)
}
