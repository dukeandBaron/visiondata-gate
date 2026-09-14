package io.visiondata.gate.gateway;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "visiondata.fastapi-base-url=http://127.0.0.1:65534"
)
class VisionDataGatewayApplicationTest {

    @Test
    void applicationContextStartsOnLoopbackConfiguration() {
        // Context startup is the assertion.
    }
}
