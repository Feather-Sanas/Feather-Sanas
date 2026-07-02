# Front-end on Amplify Hosting. Amplify builds from the repo's amplify.yml, which
# bakes the backend origin into config.js from SAN_API_BASE at deploy time.
# (Amplify can't run the backend — see DEPLOY_AWS.md.)
resource "aws_amplify_app" "ui" {
  count        = var.enable_amplify ? 1 : 0
  name         = "${var.project}-ui"
  repository   = var.github_repository
  access_token = var.github_access_token
  platform     = "WEB"

  # Point the static UI at the HTTPS backend. amplify.yml writes this into config.js.
  environment_variables = {
    SAN_API_BASE = "https://${local.api_fqdn}"
  }

  # SPA-style fallback so deep links resolve to index.html.
  custom_rule {
    source = "/<*>"
    target = "/index.html"
    status = "404-200"
  }
}

resource "aws_amplify_branch" "main" {
  count             = var.enable_amplify ? 1 : 0
  app_id            = aws_amplify_app.ui[0].id
  branch_name       = var.github_branch
  stage             = "PRODUCTION"
  enable_auto_build = true
}

# Optional custom domain for the UI (app.<domain>). Amplify provisions the cert
# and the validation records in the same Route 53 zone.
resource "aws_amplify_domain_association" "ui" {
  count       = var.enable_amplify && var.app_subdomain != "" ? 1 : 0
  app_id      = aws_amplify_app.ui[0].id
  domain_name = var.domain_name

  # Don't block `terraform apply` on cert/DNS validation (can take many minutes to
  # hours) — Amplify completes it asynchronously.
  wait_for_verification = false

  sub_domain {
    branch_name = aws_amplify_branch.main[0].branch_name
    prefix      = var.app_subdomain
  }
}
