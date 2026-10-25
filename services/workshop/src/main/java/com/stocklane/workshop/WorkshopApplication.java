package com.stocklane.workshop;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;
@SpringBootApplication(scanBasePackages="com.stocklane") @EnableScheduling
public class WorkshopApplication{public static void main(String[]args){SpringApplication.run(WorkshopApplication.class,args);}}
