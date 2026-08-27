resource "aws_db_subnet_group" "data_platform" {
  name       = "${local.name_prefix}-database"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${local.name_prefix}-database"
  }
}

resource "aws_security_group" "database" {
  name_prefix = "${local.name_prefix}-database-"
  description = "PostgreSQL access from approved worker security groups"
  vpc_id      = aws_vpc.data_platform.id

  egress {
    description = "Database response traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = {
    Name = "${local.name_prefix}-database"
  }
}

resource "aws_vpc_security_group_ingress_rule" "database_clients" {
  for_each = var.database_client_security_group_ids

  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = each.value
  description                  = "PostgreSQL from approved data-platform worker"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_db_instance" "data_platform" {
  identifier = local.name_prefix

  engine         = "postgres"
  engine_version = "16"
  instance_class = var.database_instance_class
  db_name        = "data_platform"
  username       = "platform_admin"
  port           = 5432

  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.data.key_id

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.data.arn

  db_subnet_group_name   = aws_db_subnet_group.data_platform.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = var.database_multi_az

  backup_retention_period    = 7
  backup_window              = "03:00-04:00"
  maintenance_window         = "Sun:04:00-Sun:05:00"
  auto_minor_version_upgrade = true
  apply_immediately          = false

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  performance_insights_enabled    = false

  deletion_protection       = var.protect_database
  skip_final_snapshot       = !var.protect_database
  final_snapshot_identifier = var.protect_database ? "${local.name_prefix}-final" : null

  tags = {
    Name = local.name_prefix
  }
}
