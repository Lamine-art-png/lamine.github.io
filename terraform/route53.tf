data "aws_route53_zone" "root" {
  name         = "agroai-pilot.com."
  private_zone = false
}

resource "aws_route53_record" "api" {
  zone_id = data.aws_route53_zone.root.zone_id
  name    = "api.agroai-pilot.com"
  type    = "A"

  allow_overwrite = true

  alias {
    name                   = aws_lb.api.dns_name
    zone_id                = aws_lb.api.zone_id
    evaluate_target_health = false
  }
}
