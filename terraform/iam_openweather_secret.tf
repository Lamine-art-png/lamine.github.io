data "aws_iam_role" "ecs_exec" {
  name = "ecsTaskExecutionRole-agroai-manulife-pilot"
}

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
  role       = data.aws_iam_role.ecs_exec.name
  policy_arn = aws_iam_policy.ecs_openweather_secret.arn
}
