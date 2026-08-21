FROM public.ecr.aws/lambda/python:3.11

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

CMD ["src.lambda_handler.handler"]
