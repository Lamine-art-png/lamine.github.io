output "cluster_name"      { value = aws_ecs_cluster.pilot.name }
output "service_name"      { value = aws_ecs_service.svc.name }
output "task_definition"   { value = aws_ecs_task_definition.app.arn }
output "security_group_id" { value = aws_security_group.ecs_tasks.id }
