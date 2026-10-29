package com.stocklane.inventory.service;

import com.stocklane.inventory.dto.PersonInput;
import com.stocklane.inventory.exception.ConflictException;
import com.stocklane.inventory.exception.NotFoundException;
import com.stocklane.inventory.repository.PersonRepository;
import java.time.Instant;
import java.util.*;
import org.springframework.stereotype.Service;

/** The people who receive parts at the storeroom counter; each gets a QR card. */
@Service
public class PeopleService {
 private final PersonRepository people;private final Commands commands;
 public PeopleService(PersonRepository people,Commands commands){this.people=people;this.commands=commands;}
 public List<Map<String,Object>> list(){return people.findActive();}
 public Map<String,Object> add(String key,PersonInput input){
  return commands.execute(key,"add-person",input,()->{
   String name=input==null||input.name()==null?"":input.name().trim().replaceAll("\\s+"," ");
   if(name.isEmpty()||name.length()>80)throw new IllegalArgumentException("Enter a name (maximum 80 characters)");
   if(people.nameExists(name))throw new ConflictException(name+" is already on the list");
   String id=UUID.randomUUID().toString();people.insert(id,name,Instant.now().toString());
   return people.findById(id).orElseThrow();
  });
 }
 public Map<String,Object> remove(String id){
  people.findById(id).orElseThrow(()->new NotFoundException("Person not found"));
  people.deactivate(id);return Map.of("id",id,"active",false);
 }
 /** An active receiver, or an error the counter screen can show. */
 public Map<String,Object> active(String id){
  var person=people.findById(id).orElseThrow(()->new IllegalArgumentException("Choose who receives the part"));
  if(!Boolean.TRUE.equals(person.get("active")))throw new ConflictException(person.get("name")+" is no longer on the list");
  return person;
 }
}
