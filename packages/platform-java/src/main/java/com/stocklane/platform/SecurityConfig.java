package com.stocklane.platform;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
import org.springframework.core.env.Environment;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.core.*;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.oauth2.server.resource.authentication.*;
import org.springframework.security.oauth2.server.resource.web.DefaultBearerTokenResolver;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.AnonymousAuthenticationFilter;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.cors.*;

@Configuration
@EnableMethodSecurity
public class SecurityConfig {
 @Bean UrlBasedCorsConfigurationSource corsConfigurationSource(@Value("${app.web-origin:http://localhost:4173}")String origin){var config=new CorsConfiguration();config.setAllowedOrigins(List.of(origin));config.setAllowedMethods(List.of("GET","POST","PUT","PATCH","OPTIONS"));config.setAllowedHeaders(List.of("Authorization","Content-Type","Idempotency-Key","X-Demo-User"));var source=new UrlBasedCorsConfigurationSource();source.registerCorsConfiguration("/api/**",config);return source;}
 @Bean SecurityFilterChain security(HttpSecurity http, Environment env,
     UrlBasedCorsConfigurationSource corsConfigurationSource,
     @Value("${app.auth-mode:cognito}") String mode,
     @Value("${app.internal-token}") String internal,
     @Value("${app.cognito-issuer:}") String issuer,
     @Value("${app.cognito-clients:}") String clients,
     @Value("${app.inventory-read-token:}")String inventoryRead,
     @Value("${app.inventory-control-token:}")String inventoryControl) throws Exception {
   boolean local=mode.equals("local");
   if(local && (!Arrays.asList(env.getActiveProfiles()).contains("local")||"cloud".equals(env.getProperty("ENVIRONMENT")))) throw new IllegalStateException("Local authentication requires the explicit local profile outside cloud environments");
   if(internal.length()<32) throw new IllegalStateException("INTERNAL_TOKEN must contain at least 32 characters");
   String service=env.getProperty("spring.application.name","");
   if(!local&&("inventory".equals(service)&&(inventoryRead.length()<32||inventoryControl.length()<32)||"workshop".equals(service)&&inventoryControl.length()<32))throw new IllegalStateException("Configure separate internal read/control capability tokens");
   http.cors(cors -> cors.configurationSource(corsConfigurationSource)).csrf(c->c.disable()).sessionManagement(s->s.sessionCreationPolicy(SessionCreationPolicy.STATELESS));
   http.authorizeHttpRequests(a->a.requestMatchers("/actuator/health/**").permitAll()
      .requestMatchers("/internal/**","/actuator/prometheus").permitAll().anyRequest().authenticated());
   http.addFilterBefore(new OncePerRequestFilter(){
    @Override protected void doFilterInternal(HttpServletRequest req,HttpServletResponse res,FilterChain chain) throws ServletException,IOException {
     if(req.getRequestURI().startsWith("/internal/")||req.getRequestURI().equals("/actuator/prometheus")){
      boolean metrics=req.getRequestURI().equals("/actuator/prometheus");
      String required=internal;
      if(!local&&!metrics){
       if(!"inventory".equals(service)){res.sendError(404);return;}
       if(req.getMethod().equals("GET"))required=inventoryRead;
       else if(req.getRequestURI().startsWith("/internal/jobs/"))required=inventoryControl;
       else{res.sendError(404);return;}
      }
      String supplied=metrics?Objects.toString(req.getHeader("Authorization"),"").replaceFirst("^Bearer ",""):Objects.toString(req.getHeader("X-Internal-Token"),"");
      if(!MessageDigest.isEqual(required.getBytes(StandardCharsets.UTF_8),supplied.getBytes(StandardCharsets.UTF_8))){res.sendError(401);return;}
      SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken("service",null,List.of(new SimpleGrantedAuthority("ROLE_SERVICE"))));
     } else if(local){
      String role="mechanic".equals(req.getHeader("X-Demo-User"))?"MECHANIC":"OWNER";
      SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken("local-"+role.toLowerCase(),null,List.of(new SimpleGrantedAuthority("ROLE_"+role))));
     }
     chain.doFilter(req,res);
    }
   },AnonymousAuthenticationFilter.class);
   if(!local){
    if(issuer.isBlank()||clients.isBlank()) throw new IllegalStateException("Cognito issuer and allowed client IDs are required");
    NimbusJwtDecoder decoder=JwtDecoders.fromIssuerLocation(issuer);
    Set<String> allowed=new HashSet<>(Arrays.asList(clients.split(",")));
    OAuth2TokenValidator<Jwt> claims=jwt->"access".equals(jwt.getClaimAsString("token_use")) && allowed.contains(jwt.getClaimAsString("client_id"))
      ?OAuth2TokenValidatorResult.success():OAuth2TokenValidatorResult.failure(new OAuth2Error("invalid_token","Invalid token use or client",null));
    decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(JwtValidators.createDefaultWithIssuer(issuer),claims));
    JwtAuthenticationConverter converter=new JwtAuthenticationConverter();
    converter.setJwtGrantedAuthoritiesConverter(jwt->{
      List<org.springframework.security.core.GrantedAuthority> a=new ArrayList<>(new JwtGrantedAuthoritiesConverter().convert(jwt));
      List<String> groups=jwt.getClaimAsStringList("cognito:groups");
      if(groups!=null)groups.forEach(g->a.add(new SimpleGrantedAuthority("ROLE_"+g)));
      return a;
    });
    // Prometheus uses the internal scrape token in the Authorization header.
    // Leave that exact endpoint to the constant-time token check above, rather
    // than attempting to decode the opaque token as a Cognito JWT first.
    var bearerTokens=new DefaultBearerTokenResolver();
    http.oauth2ResourceServer(o->o
      .bearerTokenResolver(req->"/actuator/prometheus".equals(req.getRequestURI())?null:bearerTokens.resolve(req))
      .jwt(j->j.decoder(decoder).jwtAuthenticationConverter(converter)));
   }
   return http.build();
 }
}
