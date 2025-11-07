data "aws_acm_certificate" "api" {
  domain      = "api.agroai-pilot.com"
  statuses    = ["ISSUED"]
  most_recent = true
}
