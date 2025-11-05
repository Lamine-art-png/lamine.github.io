output "cluster_name"   { value = aws_ecs_cluster.pilot.name }
output "service_name"   { value = aws_ecs_service.svc.name }
output "task_family"    { value = aws_ecs_task_definition.app.family }
output "log_group_name" { value = aws_cloudwatch_log_group.ecs.name }
