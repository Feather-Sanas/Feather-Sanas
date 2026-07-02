output "backend_url" {
  description = "HTTPS backend origin. Set this as PUBLIC_BASE_URL in the .env secret and as the Twilio Voice/TwiML URLs' host."
  value       = "https://${local.api_fqdn}"
}

output "backend_public_ip" {
  description = "Elastic IP of the EC2 backend (the API A record points here)."
  value       = aws_eip.backend.public_ip
}

output "instance_id" {
  description = "EC2 instance id — open a shell with: aws ssm start-session --target <id>"
  value       = aws_instance.backend.id
}

output "env_secret_name" {
  description = "Secrets Manager secret to populate with the full server/.env contents (see README step 2)."
  value       = aws_secretsmanager_secret.env.name
}

output "sdk_bucket" {
  description = "S3 bucket to upload the Sanas Linux x86-64 SDK tarball into (as sdk_object_key)."
  value       = aws_s3_bucket.sdk.bucket
}

output "sdk_upload_command" {
  description = "Copy-paste to upload the SDK tarball."
  value       = "aws s3 cp <your-local>/${var.sdk_object_key} s3://${aws_s3_bucket.sdk.bucket}/${var.sdk_object_key} --region ${var.region}"
}

output "amplify_default_domain" {
  description = "Default Amplify UI URL (branch subdomain of this)."
  value       = var.enable_amplify ? aws_amplify_app.ui[0].default_domain : null
}

output "amplify_branch_url" {
  description = "The live UI URL on the deployed branch."
  value       = var.enable_amplify ? "https://${var.github_branch}.${aws_amplify_app.ui[0].default_domain}" : null
}

output "ses_smtp_host" {
  description = "SMTP_HOST for the .env secret."
  value       = var.enable_ses ? "email-smtp.${var.region}.amazonaws.com" : null
}

output "ses_smtp_user" {
  description = "SMTP_USER for the .env secret (SES SMTP username)."
  value       = var.enable_ses ? aws_iam_access_key.ses[0].id : null
}

output "ses_smtp_password" {
  description = "SMTP_PASS for the .env secret (SES SMTP password). Sensitive: read with `terraform output -raw ses_smtp_password`."
  value       = var.enable_ses ? aws_iam_access_key.ses[0].ses_smtp_password_v4 : null
  sensitive   = true
}
