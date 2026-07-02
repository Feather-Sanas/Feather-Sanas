data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  common_tags = merge({
    Project   = var.project
    ManagedBy = "terraform"
  }, var.tags)

  api_fqdn   = "${var.api_subdomain}.${var.domain_name}"
  ses_domain = var.ses_domain != "" ? var.ses_domain : var.domain_name
  sdk_bucket = "${var.project}-sdk-${data.aws_caller_identity.current.account_id}-${var.region}"
}
