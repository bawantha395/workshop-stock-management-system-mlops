package com.stocklane.platform;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import com.sun.net.httpserver.HttpServer;
import jakarta.servlet.Filter;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.List;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.junit.jupiter.web.SpringJUnitWebConfig;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.context.WebApplicationContext;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** Run the real cloud-mode filter chain, including JWT decoding, without AWS. */
@SpringJUnitWebConfig({SecurityConfig.class, MetricsSecurityTest.WebConfig.class})
@TestPropertySource(properties = {
    "app.auth-mode=cognito", "spring.application.name=inventory",
    "app.internal-token=metrics-internal-token-0123456789-abcdef",
    "app.inventory-read-token=read-capability-token-0123456789-abcdef",
    "app.inventory-control-token=control-capability-token-0123456789-abcdef",
    "app.cognito-clients=test-client"
})
class MetricsSecurityTest {
    private static final String SCRAPE_TOKEN = "metrics-internal-token-0123456789-abcdef";
    private static final RSAKey KEY = signingKey();
    private static final HttpServer SERVER = issuerServer();
    private static final String ISSUER = "http://127.0.0.1:" + SERVER.getAddress().getPort();

    @Autowired WebApplicationContext context;
    private MockMvc http;

    @DynamicPropertySource
    static void issuerProperty(DynamicPropertyRegistry properties) {
        properties.add("app.cognito-issuer", () -> ISSUER);
    }

    @BeforeEach
    void configureFilterChain() {
        http = MockMvcBuilders.webAppContextSetup(context)
            .addFilters(context.getBean("springSecurityFilterChain", Filter.class)).build();
    }

    @AfterAll static void stopIssuer() { SERVER.stop(0); }

    @Test void correctOpaqueScrapeTokenReturnsMetrics() throws Exception {
        http.perform(get("/actuator/prometheus").header("Authorization", "Bearer " + SCRAPE_TOKEN))
            .andExpect(status().isOk()).andExpect(content().string("test_metric 1\n"));
    }

    @Test void missingScrapeTokenIsRejected() throws Exception {
        http.perform(get("/actuator/prometheus")).andExpect(status().isUnauthorized());
    }

    @Test void wrongScrapeTokenIsRejected() throws Exception {
        http.perform(get("/actuator/prometheus").header("Authorization", "Bearer wrong-token"))
            .andExpect(status().isUnauthorized());
    }

    @Test void cognitoTokenCannotReplaceTheMetricsSecret() throws Exception {
        http.perform(get("/actuator/prometheus").header("Authorization", "Bearer " + jwt("test-client", "OWNER", 120)))
            .andExpect(status().isUnauthorized());
    }

    @Test void metricsTokenDoesNotAuthorizeApplicationApis() throws Exception {
        http.perform(get("/api/probe").header("Authorization", "Bearer " + SCRAPE_TOKEN))
            .andExpect(status().isUnauthorized());
    }

    @Test void applicationApisStillRequireAuthentication() throws Exception {
        http.perform(get("/api/probe")).andExpect(status().isUnauthorized());
    }

    @Test void validSignedCognitoClaimsStillAuthorizeTheOwner() throws Exception {
        http.perform(get("/api/probe").header("Authorization", "Bearer " + jwt("test-client", "OWNER", 120)))
            .andExpect(status().isOk()).andExpect(content().string("owner"));
    }

    @Test void signedTokensForOtherClientsAreRejected() throws Exception {
        http.perform(get("/api/probe").header("Authorization", "Bearer " + jwt("another-client", "OWNER", 120)))
            .andExpect(status().isUnauthorized());
    }

    @Test void expiredSignedTokensAreRejected() throws Exception {
        http.perform(get("/api/probe").header("Authorization", "Bearer " + jwt("test-client", "OWNER", -120)))
            .andExpect(status().isUnauthorized());
    }

    @Test void mechanicDoesNotReceiveOwnerPermissions() throws Exception {
        http.perform(get("/api/probe").header("Authorization", "Bearer " + jwt("test-client", "MECHANIC", 120)))
            .andExpect(status().isForbidden());
    }

    private static String jwt(String client, String group, int lifetime) throws Exception {
        Instant now = Instant.now();
        var claims = new JWTClaimsSet.Builder().issuer(ISSUER).subject("test-user")
            .issueTime(Date.from(now.minusSeconds(180)))
            .expirationTime(Date.from(now.plusSeconds(lifetime)))
            .claim("token_use", "access").claim("client_id", client)
            .claim("cognito:groups", List.of(group)).build();
        var jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).keyID(KEY.getKeyID()).build(), claims);
        jwt.sign(new RSASSASigner(KEY));
        return jwt.serialize();
    }

    private static RSAKey signingKey() {
        try { return new RSAKeyGenerator(2048).keyID("test-signing-key").generate(); }
        catch (Exception error) { throw new IllegalStateException(error); }
    }

    private static HttpServer issuerServer() {
        try {
            var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext("/", exchange -> {
                String body = "/jwks".equals(exchange.getRequestURI().getPath())
                    ? new JWKSet(KEY.toPublicJWK()).toString()
                    : "{\"issuer\":\"" + ISSUER + "\",\"jwks_uri\":\"" + ISSUER + "/jwks\","
                      + "\"authorization_endpoint\":\"" + ISSUER + "/authorize\","
                      + "\"token_endpoint\":\"" + ISSUER + "/token\","
                      + "\"response_types_supported\":[\"code\"],\"subject_types_supported\":[\"public\"],"
                      + "\"id_token_signing_alg_values_supported\":[\"RS256\"]}";
                byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, bytes.length);
                try (var out = exchange.getResponseBody()) { out.write(bytes); }
            });
            server.start();
            return server;
        } catch (Exception error) { throw new IllegalStateException(error); }
    }

    @Configuration
    @EnableWebSecurity
    @EnableWebMvc
    @Import(Endpoints.class)
    static class WebConfig {}

    @RestController
    static class Endpoints {
        @GetMapping(value = "/actuator/prometheus", produces = "text/plain")
        public String metrics() { return "test_metric 1\n"; }

        @GetMapping("/api/probe")
        @PreAuthorize("hasRole('OWNER')")
        public String api() { return "owner"; }
    }
}
