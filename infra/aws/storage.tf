# Private bucket for the Sanas Linux x86-64 SDK tarball. It can't live in Git
# (licensed native binary), so you upload it here and the instance pulls it into
# server/vendor/ before `docker compose up --build`. Without it the backend
# builds in MOCK mode (no real Sanas processing).
resource "aws_s3_bucket" "sdk" {
  bucket        = local.sdk_bucket
  force_destroy = true # demo: allow `terraform destroy` to remove the tarball too
  tags          = { Name = "${var.project}-sdk" }
}

resource "aws_s3_bucket_ownership_controls" "sdk" {
  bucket = aws_s3_bucket.sdk.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "sdk" {
  bucket                  = aws_s3_bucket.sdk.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sdk" {
  bucket = aws_s3_bucket.sdk.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
