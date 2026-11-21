# Demo de Novara RouteOps en AWS

Configuración preparada; despliegue público pendiente. La imagen Linux del perfil alojado pasó el ensayo local de autenticación, importación, corrección, planificación y exportación. No hay una URL pública verificada. Los detalles de acceso, identificadores del proyecto e historial de soporte son locales y no forman parte de esta guía.

La región seleccionada de este proyecto es `us-east-2`. El catálogo de herramientas puede usar `us-east-1`; los recursos regionales de la aplicación deben permanecer en `us-east-2`. Verifica región, permisos, plan, cuotas y gasto en AWS Settings antes de crear recursos. Esta guía describe los pasos preparados, no afirma que se hayan ejecutado.

## Infraestructura

[infra/aws/demo.json](../infra/aws/demo.json) crea un servicio ECS Express Mode con 1 vCPU, 2 GB, una tarea, `/health` y puerto 10000. Incluye roles de ejecución/infraestructura y genera una contraseña aleatoria de 48 caracteres en Secrets Manager. La tarea solo recibe permiso de lectura para ese secreto. No se incorpora la contraseña al repositorio ni a los parámetros de CloudFormation.

Se usa ECS Express Mode porque AWS App Runner cerró el alta a clientes nuevos. [Aviso de AWS](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html). Express Mode administra el balanceador y el acceso HTTPS; requiere una VPC predeterminada con subredes públicas en la región elegida. [Guía oficial](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-getting-started.html).

La demo conserva estado dentro de un proceso. Se fija una tarea y un worker; los reinicios y las revisiones de despliegue invalidan sesiones. No actualizar mientras se realiza una prueba. Esta configuración genera cargos de infraestructura mientras esté activa; revisar los recursos y precios en la cuenta antes de crearla.

## Construcción y publicación de la imagen

Requisitos: AWS CLI actual con ECS Express Mode, Docker con Buildx, sesión AWS autorizada, permisos para ECR/CloudFormation/IAM/ECS/Secrets Manager y región con soporte del servicio y VPC predeterminada. Selecciona el perfil y región de prueba del usuario antes de ejecutar. No uses credenciales estáticas en archivos del proyecto.

```sh
export AWS_PROFILE=novara-routeops
export AWS_REGION=us-east-2
aws sts get-caller-identity
aws ecr create-repository --repository-name novara-routeops-demo --image-tag-mutability IMMUTABLE
NOVARA_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
NOVARA_REGISTRY="${NOVARA_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
NOVARA_IMAGE_TAG="preparation-$(date +%Y%m%d%H%M%S)"
aws ecr get-login-password | docker login --username AWS --password-stdin "$NOVARA_REGISTRY"
docker buildx build --platform linux/amd64 --target render-demo \
  --tag "$NOVARA_REGISTRY/novara-routeops-demo:$NOVARA_IMAGE_TAG" --push .
NOVARA_DIGEST=$(aws ecr describe-images --repository-name novara-routeops-demo \
  --image-ids imageTag="$NOVARA_IMAGE_TAG" --query 'imageDetails[0].imageDigest' --output text)
NOVARA_IMAGE_URI="$NOVARA_REGISTRY/novara-routeops-demo@$NOVARA_DIGEST"
```

Si el repositorio ya existe, reutilízalo. La etiqueta debe ser nueva. La imagen excluye `.env`, bases de datos, Excel y `data/real/` mediante la lista explícita de `.dockerignore`.

Antes del despliegue, descarga esa imagen y ensáyala en loopback con el procedimiento de [deployment-render.md](deployment-render.md), adaptando el nombre de imagen. Ejecuta la prueba `frontend/tests/hosted.mjs`. Los resultados de macOS no sustituyen este ensayo Linux.

## Crear la prueba

Valida la plantilla y revisa el cambio antes de ejecutarlo:

```sh
aws cloudformation validate-template --template-body file://infra/aws/demo.json
aws cloudformation create-change-set --stack-name novara-routeops-demo \
  --change-set-name preparation-demo --change-set-type CREATE \
  --template-body file://infra/aws/demo.json --capabilities CAPABILITY_IAM \
  --parameters ParameterKey=ImageUri,ParameterValue="$NOVARA_IMAGE_URI"
aws cloudformation describe-change-set --stack-name novara-routeops-demo --change-set-name preparation-demo
```

Una vez revisado el cambio concreto en la cuenta autorizada:

```sh
aws cloudformation execute-change-set --stack-name novara-routeops-demo --change-set-name preparation-demo
aws cloudformation describe-stacks --stack-name novara-routeops-demo --query 'Stacks[0].Outputs'
```

Consulta `DemoServiceArn` con `aws ecs describe-express-gateway-service --service-arn ...` para obtener el estado y el endpoint HTTPS. Recupera la clave desde el secreto indicado por `PasswordSecretArn` en la consola de Secrets Manager; compártela por separado de la URL.

Verifica `/health`, acceso con clave, pantalla Preparación con factores bloqueados, descarga e importación de ambas nóminas ficticias, corrección de comunas, ponderación conjunta y Excel con Supuestos. Repite la ponderación cambiando la carga, manteniendo el resto de factores. Los datos arbitrarios o archivos modificados se rechazan en esta demo.

Para cerrar la prueba, revisa y elimina el stack desde CloudFormation. Revisa también imágenes ECR y recursos retenidos: el repositorio se creó aparte y Secrets Manager puede conservar el secreto durante su período de recuperación. No se automatiza la eliminación de recursos existentes del usuario.

Referencias del contrato de infraestructura: [servicio Express](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ecs-expressgatewayservice.html), [contenedor y secretos](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-ecs-expressgatewayservice-expressgatewaycontainer.html), [límites de tareas](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-ecs-expressgatewayservice-expressgatewayscalingtarget.html).
