resource "aws_ecr_repository" "pipeline" {
  count = var.enable_ecs_runtime ? 1 : 0

  name                 = "${local.name_prefix}-pipeline"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.data.arn
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "pipeline" {
  count = var.enable_ecs_runtime ? 1 : 0

  repository = aws_ecr_repository.pipeline[0].name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Remove untagged images after seven days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Retain the newest twenty immutable images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 20
        }
        action = { type = "expire" }
      },
    ]
  })
}

resource "aws_ecs_cluster" "pipeline" {
  count = var.enable_ecs_runtime ? 1 : 0

  name = local.name_prefix

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_ecs_task_definition" "pipeline" {
  count = var.enable_ecs_runtime ? 1 : 0

  family                   = local.name_prefix
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_execution[0].arn
  task_role_arn            = aws_iam_role.pipeline.arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  volume {
    name = "scratch"
  }

  container_definitions = jsonencode([
    {
      name      = "pipeline"
      image     = "${aws_ecr_repository.pipeline[0].repository_url}:${var.container_image_tag}"
      essential = true
      environment = [
        { name = "DATA_PLATFORM_OPENLINEAGE_ENABLED", value = "false" },
      ]
      secrets = [
        {
          name      = "DATA_PLATFORM_DB_HOST"
          valueFrom = "${aws_db_instance.data_platform.master_user_secret[0].secret_arn}:host::"
        },
        {
          name      = "DATA_PLATFORM_DB_PORT"
          valueFrom = "${aws_db_instance.data_platform.master_user_secret[0].secret_arn}:port::"
        },
        {
          name      = "DATA_PLATFORM_DB_NAME"
          valueFrom = "${aws_db_instance.data_platform.master_user_secret[0].secret_arn}:dbname::"
        },
        {
          name      = "DATA_PLATFORM_DB_USERNAME"
          valueFrom = "${aws_db_instance.data_platform.master_user_secret[0].secret_arn}:username::"
        },
        {
          name      = "DATA_PLATFORM_DB_PASSWORD"
          valueFrom = "${aws_db_instance.data_platform.master_user_secret[0].secret_arn}:password::"
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.pipeline.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
      readonlyRootFilesystem = true
      mountPoints = [
        {
          sourceVolume  = "scratch"
          containerPath = "/tmp"
          readOnly      = false
        },
      ]
    },
  ])
}

