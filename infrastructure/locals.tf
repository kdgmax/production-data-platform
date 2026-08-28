locals {
  name_prefix = "${var.project_name}-${var.environment}"
  bucket_names = {
    landing   = "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-${var.aws_region}-landing"
    processed = "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-${var.aws_region}-processed"
  }
  alarm_actions = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]
  base_interface_services = toset([
    "kms",
    "logs",
    "secretsmanager",
  ])
  ecs_interface_services = toset([
    "ecr.api",
    "ecr.dkr",
  ])
  interface_services = setunion(
    var.enable_interface_endpoints || var.enable_ecs_runtime ? local.base_interface_services : toset([]),
    var.enable_ecs_runtime ? local.ecs_interface_services : toset([]),
  )
}

