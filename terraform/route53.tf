data "aws_route53_zone" "root" {
  name         = "agroai-pilot.com."
  private_zone = false
}
