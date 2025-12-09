data "aws_iam_policy_document" "ecs_openweather_secret" {
  statement {
    actions = [
      "secretsmanager:GetSecretValue"
    ]
    resources = [
      aws_secretsmanager_secret.openweather.arn
    ]
  }
}

resource "aws_iam_policy" "ecs_openweather_secret" {
  name   = "ecs-task-secrets-openweather"
  policy = data.aws_iam_policy_document.ecs_openweather_secret.json
}

resource "aws_iam_role_policy_attachment" "ecs_openweather_secret_attach" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = aws_iam_policy.ecs_openweather_secret.arn
}
