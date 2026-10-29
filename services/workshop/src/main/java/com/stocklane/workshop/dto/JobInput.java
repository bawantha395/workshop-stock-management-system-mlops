package com.stocklane.workshop.dto;

/** Request body for opening a repair job. */
public record JobInput(String customer,String vehicle,String registration,String phone,String summary){}
