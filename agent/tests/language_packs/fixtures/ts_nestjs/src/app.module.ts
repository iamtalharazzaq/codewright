import { Module } from "@nestjs/common";
import { GreetingsController } from "./greetings/greetings.controller";

@Module({ controllers: [GreetingsController] })
export class AppModule {}
