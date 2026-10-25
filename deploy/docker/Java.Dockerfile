FROM maven:3.9.11-amazoncorretto-21 AS build
ARG SERVICE
WORKDIR /build
COPY pom.xml ./
COPY packages ./packages
COPY services/inventory ./services/inventory
COPY services/workshop ./services/workshop
RUN mvn -B -ntp -pl services/${SERVICE} -am package -DskipTests && cp services/${SERVICE}/target/${SERVICE}-0.1.0.jar /app.jar
FROM amazoncorretto:21-al2023-headless
RUN yum install -y shadow-utils curl-minimal && yum clean all && useradd -u 10001 -m app && mkdir -p /data/invoices && chown -R 10001:10001 /data
WORKDIR /app
COPY --from=build --chown=10001:10001 /app.jar /app/app.jar
COPY deploy/certs /app/certs
USER 10001
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=70 -XX:+ExitOnOutOfMemoryError"
ENTRYPOINT ["java","-jar","/app/app.jar"]
