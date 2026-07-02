# Sani on AWS — Terraform. Provisions the split deploy from DEPLOY_AWS.md:
# Amplify (front-end) + one x86-64 EC2 backend behind Caddy (auto-HTTPS), with
# Secrets Manager (server/.env), S3 (the Sanas Linux SDK tarball), Route 53 DNS,
# and SES for demo emails.
#
# State note: `terraform apply` writes some sensitive values to state (the SES
# SMTP password, resource ARNs). Use an ENCRYPTED remote backend for anything
# beyond a throwaway demo — uncomment and fill the S3 backend below.
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # backend "s3" {
  #   bucket  = "your-tfstate-bucket"
  #   key     = "sani/aws/terraform.tfstate"
  #   region  = "us-east-1"
  #   encrypt = true
  #   # State locking: use_lockfile = true needs Terraform >= 1.10 (bump
  #   # required_version above). On older CLIs, use dynamodb_table = "..." instead.
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = local.common_tags
  }
}
