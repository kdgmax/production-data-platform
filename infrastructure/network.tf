resource "aws_vpc" "data_platform" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_subnet" "private" {
  count = 2

  vpc_id                  = aws_vpc.data_platform.id
  cidr_block              = var.private_subnet_cidrs[count.index]
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name_prefix}-private-${count.index + 1}"
    Tier = "private"
  }
}

resource "aws_route_table" "private" {
  count = 2

  vpc_id = aws_vpc.data_platform.id

  tags = {
    Name = "${local.name_prefix}-private-${count.index + 1}"
  }
}

resource "aws_route_table_association" "private" {
  count = 2

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.data_platform.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id

  tags = {
    Name = "${local.name_prefix}-s3"
  }
}

resource "aws_security_group" "endpoints" {
  name_prefix = "${local.name_prefix}-endpoints-"
  description = "TLS access to private AWS service endpoints"
  vpc_id      = aws_vpc.data_platform.id

  ingress {
    description = "HTTPS from the data-platform VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "Endpoint responses within the VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = {
    Name = "${local.name_prefix}-endpoints"
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each = local.interface_services

  vpc_id              = aws_vpc.data_platform.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]

  tags = {
    Name = "${local.name_prefix}-${each.value}"
  }
}

data "aws_prefix_list" "s3" {
  name = "com.amazonaws.${var.aws_region}.s3"
}

resource "aws_security_group" "ecs_runtime" {
  count = var.enable_ecs_runtime ? 1 : 0

  name_prefix = "${local.name_prefix}-ecs-runtime-"
  description = "No-ingress security group for on-demand pipeline tasks"
  vpc_id      = aws_vpc.data_platform.id

  tags = {
    Name = "${local.name_prefix}-ecs-runtime"
  }
}

resource "aws_vpc_security_group_egress_rule" "ecs_endpoint_https" {
  count = var.enable_ecs_runtime ? 1 : 0

  security_group_id            = aws_security_group.ecs_runtime[0].id
  referenced_security_group_id = aws_security_group.endpoints.id
  description                  = "HTTPS to private AWS service endpoints"
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "ecs_s3_https" {
  count = var.enable_ecs_runtime ? 1 : 0

  security_group_id = aws_security_group.ecs_runtime[0].id
  prefix_list_id    = data.aws_prefix_list.s3.id
  description       = "HTTPS to S3 through the gateway endpoint"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "ecs_database" {
  count = var.enable_ecs_runtime ? 1 : 0

  security_group_id            = aws_security_group.ecs_runtime[0].id
  referenced_security_group_id = aws_security_group.database.id
  description                  = "PostgreSQL to the platform database"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "ecs_dns_udp" {
  count = var.enable_ecs_runtime ? 1 : 0

  security_group_id = aws_security_group.ecs_runtime[0].id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  description       = "DNS to the VPC resolver"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "udp"
}

resource "aws_vpc_security_group_egress_rule" "ecs_dns_tcp" {
  count = var.enable_ecs_runtime ? 1 : 0

  security_group_id = aws_security_group.ecs_runtime[0].id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  description       = "TCP DNS fallback to the VPC resolver"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "tcp"
}

