package com.stocklane.workshop.exception;
import java.util.Map;
import org.springframework.dao.DataAccessException;
import org.springframework.http.*;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
@RestControllerAdvice
public class GlobalExceptionHandler {
 @ExceptionHandler(ConflictException.class) ResponseEntity<?> conflict(Exception e){return response(409,e.getMessage());}
 @ExceptionHandler(NotFoundException.class) ResponseEntity<?> missing(Exception e){return response(404,e.getMessage());}
 @ExceptionHandler({IllegalArgumentException.class,MethodArgumentNotValidException.class}) ResponseEntity<?> bad(Exception e){return response(400,e instanceof MethodArgumentNotValidException?"Check the required fields and quantities":e.getMessage());}
 @ExceptionHandler(DataAccessException.class) ResponseEntity<?> data(Exception e){return response(409,"The change could not be saved. Refresh the record and retry with the same request key.");}
 private ResponseEntity<?> response(int status,String message){return ResponseEntity.status(status).body(Map.of("status",status,"message",message));}
}
