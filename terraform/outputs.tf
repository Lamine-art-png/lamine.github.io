output "db_address" { value = module.db.db_instance_address }
output "ecr_repo"   { value = aws_ecr_repository.api.repository_url }
output "cluster_arn"{ value = module.ecs.cluster_arn }
