variable "region" {
  description = "AWS region. SES SMTP host is derived from this. us-east-1 matches DEPLOY_AWS.md."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Short name prefixed onto resource names/tags."
  type        = string
  default     = "sani"
}

# ---- DNS / domain (you own this; it must be a Route 53 hosted zone) ----------
variable "domain_name" {
  description = "Root domain that is ALREADY a Route 53 hosted zone in this account, e.g. sani-demo.com."
  type        = string
}

variable "api_subdomain" {
  description = "Subdomain for the backend API (Caddy auto-issues its cert). Backend = <api_subdomain>.<domain_name>."
  type        = string
  default     = "api"
}

variable "app_subdomain" {
  description = "Optional custom subdomain for the Amplify UI (e.g. app). Empty = use the default *.amplifyapp.com URL."
  type        = string
  default     = ""
}

# ---- Backend host (EC2) ------------------------------------------------------
variable "instance_type" {
  description = "x86-64 instance type (the Sanas SDK is x86-64 — NOT Graviton). t3.medium gives ASR/Whisper more headroom."
  type        = string
  default     = "t3.small"
}

variable "root_volume_gb" {
  description = "Root EBS gp3 size in GB."
  type        = number
  default     = 20
}

variable "ssh_ingress_cidr" {
  description = "CIDR allowed to reach port 22 (e.g. 203.0.113.4/32). Empty = no SSH port opened; use SSM Session Manager instead."
  type        = string
  default     = ""
}

variable "key_pair_name" {
  description = "Existing EC2 key pair name for SSH. Empty = no key (use SSM Session Manager)."
  type        = string
  default     = ""
}

# ---- App source + Amplify ----------------------------------------------------
variable "github_repository" {
  description = "HTTPS Git URL the EC2 box clones and Amplify connects to."
  type        = string
  default     = "https://github.com/Feather-Sanas/Feather-Sanas"
}

variable "github_branch" {
  description = "Branch to deploy."
  type        = string
  default     = "main"
}

variable "enable_amplify" {
  description = "Provision the Amplify front-end app. False = deploy backend only (host the UI elsewhere)."
  type        = bool
  default     = true
}

variable "github_access_token" {
  description = "GitHub PAT with repo + admin:repo_hook scope, so Amplify can connect the repo and create its webhook. Only needed when enable_amplify = true."
  type        = string
  default     = ""
  sensitive   = true
}

# ---- Secrets + SDK artifact --------------------------------------------------
variable "secret_name" {
  description = "Secrets Manager secret that holds the full server/.env (you populate it out-of-band — see README)."
  type        = string
  default     = "sani/env"
}

variable "sdk_object_key" {
  description = "S3 key of the Sanas Linux x86-64 SDK tarball you upload. Without it the backend builds in MOCK mode."
  type        = string
  default     = "sanas_remote_sdk_linux_x86-64.tar.gz"
}

# ---- Email (SES) -------------------------------------------------------------
variable "enable_ses" {
  description = "Provision SES (domain identity + DKIM) and an SMTP-credential IAM user for book-a-demo emails."
  type        = bool
  default     = true
}

variable "ses_domain" {
  description = "Domain to verify for SES sending. Empty = use domain_name."
  type        = string
  default     = ""
}

variable "notify_email" {
  description = "Internal booking-notification address. Verified as an SES email identity so it works even while SES is in sandbox mode."
  type        = string
  default     = "chris.featherstone@sanas.ai"
}

variable "tags" {
  description = "Extra tags merged onto every resource."
  type        = map(string)
  default     = {}
}
