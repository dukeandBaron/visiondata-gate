package io.visiondata.gate.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.net.URI;
import java.util.concurrent.TimeUnit;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.reactive.function.client.WebClient;

class FastApiProxyHandlerTest {

    private MockWebServer upstream;
    private WebTestClient client;

    @BeforeEach
    void setUp() throws Exception {
        upstream = new MockWebServer();
        upstream.start();
        URI upstreamUri = upstream.url("/").uri();
        FastApiProxyHandler handler = new FastApiProxyHandler(
                WebClient.builder().build(),
                upstreamUri
        );
        client = WebTestClient.bindToController(handler).build();
    }

    @AfterEach
    void tearDown() throws Exception {
        if (upstream != null) {
            upstream.shutdown();
        }
    }

    @Test
    void proxiesMethodPathQueryHeadersAndRawBody() throws Exception {
        upstream.enqueue(new MockResponse()
                .setResponseCode(202)
                .addHeader("Content-Type", "application/json")
                .addHeader("X-Upstream-Receipt", "receipt-17")
                .setBody("{\"status\":\"accepted\"}"));

        byte[] payload = "--boundary\r\nraw-image-bytes\r\n--boundary--".getBytes();
        client.post()
                .uri("/v1/assets?workspace=wsp_local")
                .header("X-Actor-User-Id", "usr_local_demo")
                .header("Connection", "keep-alive")
                .contentType(MediaType.parseMediaType("multipart/form-data; boundary=boundary"))
                .bodyValue(payload)
                .exchange()
                .expectStatus().isAccepted()
                .expectHeader().valueEquals("X-Upstream-Receipt", "receipt-17")
                .expectHeader().valueEquals("X-VisionData-Gateway", "spring-webflux")
                .expectBody().json("{\"status\":\"accepted\"}");

        RecordedRequest request = upstream.takeRequest(1, TimeUnit.SECONDS);
        assertThat(request).isNotNull();
        assertThat(request.getMethod()).isEqualTo("POST");
        assertThat(request.getPath()).isEqualTo("/v1/assets?workspace=wsp_local");
        assertThat(request.getHeader("X-Actor-User-Id")).isEqualTo("usr_local_demo");
        assertThat(request.getHeader("Connection")).isNotEqualTo("keep-alive");
        assertThat(request.getBody().readByteArray()).isEqualTo(payload);
    }

    @Test
    void gatewayHealthIsReadyOnlyWhenFastApiIsHealthy() {
        upstream.enqueue(new MockResponse()
                .setResponseCode(200)
                .addHeader("Content-Type", "application/json")
                .setBody("{\"status\":\"ok\"}"));

        client.get()
                .uri("/gateway/v1/health")
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.status").isEqualTo("READY")
                .jsonPath("$.gateway").isEqualTo("SPRING_BOOT_WEBFLUX")
                .jsonPath("$.fastapi").isEqualTo("READY")
                .jsonPath("$.production_release_allowed").isEqualTo(false)
                .jsonPath("$.machine_write_permitted").isEqualTo(false);
    }

    @Test
    void gatewayHealthFailsClosedWhenFastApiIsNotHealthy() {
        upstream.enqueue(new MockResponse()
                .setResponseCode(503)
                .addHeader("Content-Type", "application/json")
                .setBody("{\"status\":\"starting\"}"));

        client.get()
                .uri("/gateway/v1/health")
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectBody()
                .jsonPath("$.status").isEqualTo("HOLD")
                .jsonPath("$.fastapi").isEqualTo("UNAVAILABLE")
                .jsonPath("$.production_release_allowed").isEqualTo(false);
    }

    @Test
    void proxyFailsClosedWhenFastApiCannotBeReached() throws Exception {
        upstream.shutdown();
        upstream = null;

        client.get()
                .uri("/v1/tasks")
                .exchange()
                .expectStatus().isEqualTo(503)
                .expectBody()
                .jsonPath("$.error_code").isEqualTo("FASTAPI_UPSTREAM_UNAVAILABLE")
                .jsonPath("$.production_release_allowed").isEqualTo(false)
                .jsonPath("$.machine_write_permitted").isEqualTo(false);

    }

    @Test
    void rejectsNonLoopbackFastApiUpstream() {
        assertThatThrownBy(() -> GatewayConfiguration.validateFastApiBaseUri(
                "https://example.com:443"
        ))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("loopback");
    }
}
