# Your domain must already be a hosted zone in this account (data lookup, not
# created here). A record points the API subdomain at the Elastic IP so Caddy can
# get its Let's Encrypt cert and Twilio has a stable URL.
data "aws_route53_zone" "main" {
  name = var.domain_name
}

resource "aws_route53_record" "api" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.api_fqdn
  type    = "A"
  ttl     = 300
  records = [aws_eip.backend.public_ip]
}
