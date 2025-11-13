##########################
# ECS Service autoscaling
##########################

# Target: scale the service's desired_count between 1 and 3
resource "aws_appautoscaling_target" "ecs_api" {
  max_capacity       = 3
  min_capacity       = 1
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"

  # "service/<cluster-name>/<service-name>"
  resource_id = format(
    "service/%s/%s",
    aws_ecs_cluster.api.name,
    aws_ecs_service.api.name
  )
}

# Policy: target-tracking on average CPU
resource "aws_appautoscaling_policy" "ecs_api_cpu" {
  name               = "${var.project}-cpu-autoscale"
  service_namespace  = aws_appautoscaling_target.ecs_api.service_namespace
  resource_id        = aws_appautoscaling_target.ecs_api.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs_api.scalable_dimension
  policy_type        = "TargetTrackingScaling"

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }

    # Aim for ~55% CPU
    target_value       = 55
    scale_in_cooldown  = 60
    scale_out_cooldown = 60
  }
}
