package io.visiondata.gate.gateway;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.util.UriComponentsBuilder;
import reactor.core.publisher.Mono;

@RestController
public class FastApiProxyHandler {

    private static final Set<String> HOP_BY_HOP_HEADERS = Set.of(
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade"
    );
    private static final Duration HEALTH_TIMEOUT = Duration.ofSeconds(3);

    private final WebClient webClient;
    private final URI fastApiBaseUri;

    public FastApiProxyHandler(WebClient webClient, URI fastApiBaseUri) {
        this.webClient = webClient;
        this.fastApiBaseUri = fastApiBaseUri;
    }

    @GetMapping("/gateway/v1/health")
    Mono<ResponseEntity<Map<String, Object>>> gatewayHealth() {
        URI healthUri = upstreamUri("/v1/health", null);
        return webClient.get()
                .uri(healthUri)
                .exchangeToMono(response -> {
                    int upstreamStatus = response.statusCode().value();
                    boolean ready = response.statusCode().is2xxSuccessful();
                    return response.releaseBody()
                            .thenReturn(gatewayHealthResponse(ready, upstreamStatus));
                })
                .timeout(HEALTH_TIMEOUT)
                .onErrorResume(error -> Mono.just(gatewayHealthResponse(false, 0)));
    }

    @RequestMapping(path = {"/v1", "/v1/**"})
    Mono<Void> proxy(ServerWebExchange exchange) {
        URI upstreamUri = upstreamUri(
                exchange.getRequest().getURI().getRawPath(),
                exchange.getRequest().getURI().getRawQuery()
        );
        WebClient.RequestBodySpec outgoing = webClient
                .method(exchange.getRequest().getMethod())
                .uri(upstreamUri);
        outgoing.headers(target -> copyRequestHeaders(
                exchange.getRequest().getHeaders(),
                target
        ));
        return outgoing
                .body(BodyInserters.fromDataBuffers(exchange.getRequest().getBody()))
                .exchangeToMono(response -> {
                    exchange.getResponse().setStatusCode(response.statusCode());
                    copyResponseHeaders(
                            response.headers().asHttpHeaders(),
                            exchange.getResponse().getHeaders()
                    );
                    exchange.getResponse().getHeaders().set(
                            "X-VisionData-Gateway",
                            "spring-webflux"
                    );
                    return exchange.getResponse().writeWith(
                            response.bodyToFlux(DataBuffer.class)
                    );
                })
                .onErrorResume(error -> writeUnavailableResponse(exchange));
    }

    private URI upstreamUri(String rawPath, String rawQuery) {
        return UriComponentsBuilder.fromUri(fastApiBaseUri)
                .replacePath(rawPath)
                .replaceQuery(rawQuery)
                .build(true)
                .toUri();
    }

    private ResponseEntity<Map<String, Object>> gatewayHealthResponse(
            boolean ready,
            int upstreamStatus
    ) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put(
                "schema_version",
                "visiondata-gate.local-gateway-health.v1"
        );
        payload.put("status", ready ? "READY" : "HOLD");
        payload.put("gateway", "SPRING_BOOT_WEBFLUX");
        payload.put("fastapi", ready ? "READY" : "UNAVAILABLE");
        payload.put("fastapi_status_code", upstreamStatus);
        payload.put("bind_scope", "LOOPBACK_ONLY");
        payload.put("production_release_allowed", false);
        payload.put("machine_write_permitted", false);
        return ResponseEntity
                .status(ready ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE)
                .contentType(MediaType.APPLICATION_JSON)
                .body(payload);
    }

    private Mono<Void> writeUnavailableResponse(ServerWebExchange exchange) {
        if (exchange.getResponse().isCommitted()) {
            return Mono.error(new IllegalStateException(
                    "FastAPI upstream failed after response commit"
            ));
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("error_code", "FASTAPI_UPSTREAM_UNAVAILABLE");
        payload.put("status", "HOLD");
        payload.put("detail", "The local Agent runtime is unavailable.");
        payload.put("production_release_allowed", false);
        payload.put("machine_write_permitted", false);
        byte[] serialized = ("{"
                + "\"error_code\":\"FASTAPI_UPSTREAM_UNAVAILABLE\","
                + "\"status\":\"HOLD\","
                + "\"detail\":\"The local Agent runtime is unavailable.\","
                + "\"production_release_allowed\":false,"
                + "\"machine_write_permitted\":false"
                + "}").getBytes(StandardCharsets.UTF_8);
        exchange.getResponse().setStatusCode(HttpStatus.SERVICE_UNAVAILABLE);
        exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
        exchange.getResponse().getHeaders().set(
                "X-VisionData-Gateway",
                "spring-webflux"
        );
        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(serialized);
        return exchange.getResponse().writeWith(Mono.just(buffer));
    }

    private static void copyRequestHeaders(HttpHeaders source, HttpHeaders target) {
        source.forEach((name, values) -> {
            String normalized = name.toLowerCase(Locale.ROOT);
            if (!HOP_BY_HOP_HEADERS.contains(normalized)
                    && !"host".equals(normalized)
                    && !"content-length".equals(normalized)) {
                target.addAll(name, values);
            }
        });
    }

    private static void copyResponseHeaders(HttpHeaders source, HttpHeaders target) {
        source.forEach((name, values) -> {
            String normalized = name.toLowerCase(Locale.ROOT);
            if (!HOP_BY_HOP_HEADERS.contains(normalized)) {
                target.addAll(name, values);
            }
        });
    }
}
