########################################
# OpenWeather secret (Secrets Manager)
########################################

variable "openweather_api_key" {
  type      = string
  sensitive = true
}

resource "aws_secretsmanager_secret" "openweather" {
  name = "${var.project}/openweather_api_key"

  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

resource "aws_secretsmanager_secret_version" "openweather" {
  secret_id     = aws_secretsmanager_secret.openweather.id
  secret_string = var.openweather_api_key
}

