# SES for book-a-demo / partner emails. Verifies the sending domain and publishes
# DKIM, so mail from the app is authenticated. The SMTP credentials the app uses
# come from the IAM user in iam.tf.
#
# SANDBOX: a fresh SES account can only send TO verified addresses. notify_email
# is verified below so internal notifications work immediately; to email arbitrary
# demo contacts, request SES production access in the console.
resource "aws_ses_domain_identity" "main" {
  count  = var.enable_ses ? 1 : 0
  domain = local.ses_domain
}

resource "aws_ses_domain_dkim" "main" {
  count  = var.enable_ses ? 1 : 0
  domain = aws_ses_domain_identity.main[0].domain
}

# Domain verification TXT record.
resource "aws_route53_record" "ses_verify" {
  count   = var.enable_ses ? 1 : 0
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "_amazonses.${aws_ses_domain_identity.main[0].domain}"
  type    = "TXT"
  ttl     = 600
  records = [aws_ses_domain_identity.main[0].verification_token]
}

# Easy-DKIM: three CNAMEs.
resource "aws_route53_record" "ses_dkim" {
  count   = var.enable_ses ? 3 : 0
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "${aws_ses_domain_dkim.main[0].dkim_tokens[count.index]}._domainkey.${aws_ses_domain_identity.main[0].domain}"
  type    = "CNAME"
  ttl     = 600
  records = ["${aws_ses_domain_dkim.main[0].dkim_tokens[count.index]}.dkim.amazonses.com"]
}

# Verify the internal notification address so it receives mail even in sandbox.
resource "aws_ses_email_identity" "notify" {
  count = var.enable_ses ? 1 : 0
  email = var.notify_email
}
