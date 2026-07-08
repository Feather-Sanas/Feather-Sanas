# Public 80/443 (Caddy: ACME challenge + HTTPS). SSH only if you pass a CIDR;
# otherwise reach the box via SSM Session Manager (no open port). Egress is wide
# open — the app must reach Claude, the Sanas SIP/RTP
# endpoint, an SMTP relay, and Hugging Face (first-run Whisper download).
resource "aws_security_group" "backend" {
  name_prefix = "${var.project}-backend-"
  description = "Sanas.AI backend: public 80/443, optional SSH, all egress"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP (ACME http-01 + redirect to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS (UI/API + WebSockets)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  dynamic "ingress" {
    for_each = var.ssh_ingress_cidr == "" ? [] : [var.ssh_ingress_cidr]
    content {
      description = "SSH (restricted)"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    description = "All outbound (Claude, Sanas SIP/RTP, SMTP, Hugging Face)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-backend" }

  lifecycle {
    create_before_destroy = true
  }
}
