# -*- coding: utf-8 -*-
# @Author       : William
# @Project      : TextGAN-william
# @FileName     : relgan_instructor.py
# @Time         : Created at 2019-04-25
# @Blog         : http://zhiweil.ml/
# @Description  :
# Copyrights (C) 2018. All Rights Reserved.

import torch
import torch.nn.functional as F
import torch.optim as optim
from tqdm import tqdm

import config as cfg
from instructor.real_data.instructor import BasicInstructor
from models.RGD_D import RGD_D
from models.RGD_G import RGD_G
from models.RGD_R import RGD_R
from utils.helpers import get_fixed_temperature, get_losses


class RGDInstructor(BasicInstructor):
    # the version 0
    def __init__(self, opt):
        super(RGDInstructor, self).__init__(opt)

        # generator, discriminator
        self.read = RGD_R(if_test_data=cfg.if_test)
        self.gen = RGD_G(cfg.mem_slots, cfg.num_heads, cfg.head_size, cfg.gen_embed_dim, cfg.gen_hidden_dim,
                         cfg.vocab_size, cfg.max_seq_len, cfg.padding_idx, gpu=cfg.CUDA)
        self.dis = RGD_D(cfg.dis_embed_dim, cfg.max_seq_len, cfg.num_rep, cfg.vocab_size, cfg.padding_idx,
                         gpu=cfg.CUDA)
        self.init_model()

        # Optimizer
        self.gen_opt = optim.Adam(self.gen.parameters(), lr=cfg.gen_lr)
        self.gen_adv_opt = optim.Adam(self.gen.parameters(), lr=cfg.gen_adv_lr)
        self.dis_opt = optim.Adam(self.dis.parameters(), lr=cfg.dis_lr)

    def _run(self):
        # ===PRE-TRAINING (GENERATOR)===
        if not cfg.gen_pretrain:
            self.log.info('Starting Generator MLE Training...')
            self.pretrain_generator(cfg.MLE_train_epoch)
            if cfg.if_save and not cfg.if_test:
                torch.save(self.gen.state_dict(), cfg.pretrained_gen_path)
                print('Save pretrain_generator: {}'.format(
                    cfg.pretrained_gen_path))

        # # ===ADVERSARIAL TRAINING===
        self.log.info('Starting Adversarial Training...')
        progress = tqdm(range(cfg.ADV_train_epoch))
        for adv_epoch in progress:
            self.sig.update()
            if self.sig.adv_sig:
                g_loss = self.adv_train_generator(cfg.ADV_g_step)  # Generator
                d_loss = self.adv_train_discriminator(
                    cfg.ADV_d_step)  # Discriminator
                self.update_temperature(
                    adv_epoch, cfg.ADV_train_epoch)  # update temperature

                progress.set_description(
                    'g_loss: %.4f, d_loss: %.4f, temperature: %.4f' % (g_loss, d_loss, self.gen.temperature))

                # TEST
                if adv_epoch % cfg.adv_log_step == 0:
                    self.log.info('[ADV] epoch %d: g_loss: %.4f, d_loss: %.4f, %s' % (
                        adv_epoch, g_loss, d_loss, self.cal_metrics(fmt_str=True)))

                    if cfg.if_save and not cfg.if_test:
                        self._save('ADV', adv_epoch)
            else:
                self.log.info(
                    '>>> Stop by adv_signal! Finishing adversarial training...')
                progress.close()
                break

    def _test(self):
        print('>>> Begin test...')

        self._run()
        pass

    def pretrain_generator(self, epochs):
        """
        Max Likelihood Pre-training for the generator
        """
        for epoch in range(epochs):
            self.sig.update()
            if self.sig.pre_sig:
                # ===Train===
                pre_loss = self.train_gen_epoch(
                    self.gen, self.train_data.loader, self.mle_criterion, self.gen_opt)

                # ===Test===
                if epoch % cfg.pre_log_step == 0 or epoch == epochs - 1:
                    self.log.info('[MLE-GEN] epoch %d : pre_loss = %.4f, %s' % (
                        epoch, pre_loss, self.cal_metrics(fmt_str=True)))

                    if cfg.if_save and not cfg.if_test:
                        self._save('MLE', epoch)
            else:
                self.log.info(
                    '>>> Stop by pre signal, skip to adversarial training...')
                break

    def adv_train_generator(self, g_step):
        total_loss = 0
        for step in range(g_step):
            # shape in (64, 37) index vectors
            real_samples = self.train_data.random_batch()['target']
            # but gen_samle is shape in (64, 37, 4683)
            gen_samples = self.gen.sample(
                cfg.batch_size, cfg.batch_size, one_hot=True)
            # (64, max_len)
            with torch.no_grad():
                real_struc_t, real_struc_d = self.read(real_samples)
                gen_struc_t, gen_struc_d = self.read(gen_samples)
            if cfg.CUDA:
                real_samples, gen_samples = real_samples.cuda(), gen_samples.cuda()
                real_struc_t, real_struc_d = real_struc_t.cuda(), real_struc_d.cuda()
                gen_struc_t, gen_struc_d = gen_struc_t.cuda(), gen_struc_d.cuda()
            real_samples = F.one_hot(real_samples, cfg.vocab_size).float()
            real_struc_t = F.one_hot(real_struc_t, cfg.vocab_size).float()
            gen_struc_t = F.one_hot(gen_struc_t, cfg.vocab_size).float()
            real_struc_d = F.one_hot(real_struc_d, cfg.dep_vocab_size).float()
            gen_struc_d = F.one_hot(gen_struc_d, cfg.dep_vocab_size).float()

            # ===Train===
            d_out_real = self.dis(real_samples)
            d_out_fake = self.dis(gen_samples)
            g_loss, _ = get_losses(d_out_real, d_out_fake, cfg.loss_type)

            self.optimize(self.gen_adv_opt, g_loss, self.gen)
            total_loss += g_loss.item()

        return total_loss / g_step if g_step != 0 else 0

    def adv_train_discriminator(self, d_step):
        total_loss = 0
        for step in range(d_step):
            real_samples = self.train_data.random_batch()['target']
            gen_samples = self.gen.sample(
                cfg.batch_size, cfg.batch_size, one_hot=True)
            with torch.no_grad():
                real_struc_t, real_struc_d = self.read(real_samples)
                gen_struc_t, gen_struc_d = self.read(gen_samples)
            if cfg.CUDA:
                real_samples, gen_samples = real_samples.cuda(), gen_samples.cuda()
                real_struc_t, real_struc_d = real_struc_t.cuda(), real_struc_d.cuda()
                gen_struc_t, gen_struc_d = gen_struc_t.cuda(), gen_struc_d.cuda()
            real_samples = F.one_hot(real_samples, cfg.vocab_size).float()
            real_struc_t = F.one_hot(real_struc_t, cfg.vocab_size).float()
            gen_struc_t = F.one_hot(gen_struc_t, cfg.vocab_size).float()
            real_struc_d = F.one_hot(real_struc_d, cfg.dep_vocab_size).float()
            gen_struc_d = F.one_hot(gen_struc_d, cfg.dep_vocab_size).float()

            # ===Train===
            d_out_real = self.dis(real_samples)
            d_out_fake = self.dis(gen_samples)
            _, d_loss = get_losses(d_out_real, d_out_fake, cfg.loss_type)

            self.optimize(self.dis_opt, d_loss, self.dis)
            total_loss += d_loss.item()

        return total_loss / d_step if d_step != 0 else 0

    def update_temperature(self, i, N):
        self.gen.temperature = get_fixed_temperature(
            cfg.temperature, i, N, cfg.temp_adpt)

    @staticmethod
    def optimize(opt, loss, model=None, retain_graph=False):
        opt.zero_grad()
        loss.backward(retain_graph=retain_graph)
        if model is not None:
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.clip_norm)
        opt.step()
