# Ubuntu 22.04 LTS, x86-64 (matches server/Dockerfile's FROM and the Sanas SDK).
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_instance" "backend" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.backend.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name
  key_name               = var.key_pair_name == "" ? null : var.key_pair_name

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 only
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_gb
    encrypted   = true
  }

  # Re-run the bootstrap when the template changes (e.g. after you populate the
  # secret / upload the SDK, bump anything here to force a clean rebuild).
  user_data_replace_on_change = true

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    github_repository = var.github_repository
    github_branch     = var.github_branch
    secret_name       = aws_secretsmanager_secret.env.name
    region            = var.region
    sdk_bucket        = aws_s3_bucket.sdk.bucket
    sdk_object_key    = var.sdk_object_key
    site_address      = local.api_fqdn
  })

  tags = { Name = "${var.project}-backend" }

  depends_on = [aws_iam_role_policy.instance]
}

# Stable public IP so the DNS A record survives stop/start.
resource "aws_eip" "backend" {
  domain = "vpc"
  tags   = { Name = "${var.project}-backend" }
}

resource "aws_eip_association" "backend" {
  instance_id   = aws_instance.backend.id
  allocation_id = aws_eip.backend.id
}
