FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY wedding_watch ./wedding_watch
RUN pip install --no-cache-dir .

# login / discover 는 브라우저 창이 필요하므로 호스트에서 실행하고,
# 컨테이너에는 만들어진 state/ 를 볼륨으로 넣어 주세요.
ENTRYPOINT ["wedding-watch"]
CMD ["run"]
