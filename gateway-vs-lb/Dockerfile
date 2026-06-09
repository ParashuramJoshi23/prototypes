FROM golang:1.23-alpine AS build
WORKDIR /app
COPY . .
ARG SERVICE=gateway
RUN go mod tidy && go build -o /service ./${SERVICE}

FROM alpine:3.19
COPY --from=build /service /service
ENTRYPOINT ["/service"]
