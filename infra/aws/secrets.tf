# Container for the backend's server/.env. Terraform creates it EMPTY on purpose
# — you populate the value out-of-band (see README) so real secrets never land in
# Terraform state or version control. The instance reads it at boot.
resource "aws_secretsmanager_secret" "env" {
  name                    = var.secret_name
  description             = "Sanas.AI backend server/.env (populate out-of-band; not managed by Terraform)"
  recovery_window_in_days = 0 # demo: allow immediate delete/recreate
}
