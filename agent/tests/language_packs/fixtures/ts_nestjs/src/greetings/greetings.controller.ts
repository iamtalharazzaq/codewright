import { Controller, Get, Post, Param } from "@nestjs/common";

@Controller("greetings")
export class GreetingsController {
  @Get(":id")
  findOne(@Param("id") id: string) {
    return { id };
  }

  @Post()
  create() {
    return { ok: true };
  }
}
