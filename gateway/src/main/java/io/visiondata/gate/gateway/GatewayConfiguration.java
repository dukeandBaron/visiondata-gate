package io.visiondata.gate.gateway;

import java.net.URI;
import java.util.Locale;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.cors.reactive.CorsUtils;
import org.springframework.web.server.WebFilter;

@Configuration
public class GatewayConfiguration {

    @Bean
    WebFilter upstreamCorsPreflight(FastApiProxyHandler proxy) {
        // Annotated WebFlux routes otherwise consume OPTIONS before proxy().
        // FastAPI owns the exact origin/method/header allowlist for this API.
        return (exchange, chain) -> {
            String path = exchange.getRequest().getPath().value();
            if ((path.equals("/v1") || path.startsWith("/v1/"))
                    && CorsUtils.isPreFlightRequest(exchange.getRequest())) {
                return proxy.proxy(exchange);
            }
            return chain.filter(exchange);
        };
    }

    @Bean
    URI fastApiBaseUri(
            @Value("${visiondata.fastapi-base-url:http://127.0.0.1:8787}") String value
    ) {
        return validateFastApiBaseUri(value);
    }

    @Bean
    WebClient fastApiWebClient() {
        return WebClient.builder().build();
    }

    static URI validateFastApiBaseUri(String value) {
        URI uri;
        try {
            uri = URI.create(value == null ? "" : value.trim());
        } catch (IllegalArgumentException error) {
            throw new IllegalArgumentException("FastAPI upstream URI is invalid", error);
        }
        String scheme = uri.getScheme();
        String host = uri.getHost();
        if (!"http".equalsIgnoreCase(scheme) || host == null) {
            throw new IllegalArgumentException("FastAPI upstream must use loopback HTTP");
        }
        String normalizedHost = host.toLowerCase(Locale.ROOT);
        if (!("127.0.0.1".equals(normalizedHost)
                || "localhost".equals(normalizedHost)
                || "::1".equals(normalizedHost))) {
            throw new IllegalArgumentException("FastAPI upstream must use a loopback host");
        }
        if (uri.getPort() < 1 || uri.getPort() > 65535) {
            throw new IllegalArgumentException("FastAPI upstream must include a valid port");
        }
        if (uri.getRawUserInfo() != null
                || uri.getRawQuery() != null
                || uri.getRawFragment() != null) {
            throw new IllegalArgumentException(
                    "FastAPI upstream must not contain credentials, query, or fragment"
            );
        }
        String path = uri.getRawPath();
        if (path != null && !path.isEmpty() && !"/".equals(path)) {
            throw new IllegalArgumentException("FastAPI upstream must not contain a path prefix");
        }
        String formattedHost = normalizedHost.contains(":")
                ? "[" + normalizedHost + "]"
                : normalizedHost;
        return URI.create("http://" + formattedHost + ":" + uri.getPort());
    }
}
