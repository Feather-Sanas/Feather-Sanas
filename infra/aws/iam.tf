# --- EC2 instance role: SSM Session Manager + read the .env secret + the SDK ---
resource "aws_iam_role" "instance" {
  name_prefix = "${var.project}-ec2-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# SSM Session Manager — shell into the box with no open SSH port.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Least-privilege: read exactly the one secret and the one SDK bucket.
resource "aws_iam_role_policy" "instance" {
  name = "${var.project}-instance"
  role = aws_iam_role.instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.env.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.sdk.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.sdk.arn
      },
    ]
  })
}

resource "aws_iam_instance_profile" "instance" {
  name_prefix = "${var.project}-"
  role        = aws_iam_role.instance.name
}

# --- SES SMTP credentials (book-a-demo email) ---------------------------------
# The app sends via plain SMTP (mailer.py), so SES is used through its SMTP
# interface. That needs an IAM user whose access key is converted to an SMTP
# password (ses_smtp_password_v4). Put these into the .env secret as
# SMTP_USER / SMTP_PASS (host = email-smtp.<region>.amazonaws.com, port 587).
resource "aws_iam_user" "ses" {
  count = var.enable_ses ? 1 : 0
  name  = "${var.project}-ses-smtp"
}

resource "aws_iam_user_policy" "ses" {
  count = var.enable_ses ? 1 : 0
  name  = "${var.project}-ses-send"
  user  = aws_iam_user.ses[0].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ses:SendRawEmail", "ses:SendEmail"]
      Resource = "*"
    }]
  })
}

resource "aws_iam_access_key" "ses" {
  count = var.enable_ses ? 1 : 0
  user  = aws_iam_user.ses[0].name
}
